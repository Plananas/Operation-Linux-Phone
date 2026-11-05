/* Web app behaviour: taking in what webd says, scrolling, and working out what a tap means. */
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "web_state.h"

size_t tr_web_size(void)
{
	return sizeof(tr_web);
}

size_t tr_web_status_size(void)
{
	return sizeof(tr_web_status);
}

void tr_web_init(tr_web *out)
{
	memset(out, 0, sizeof(*out));
	out->follow = 1;
}

/* The memory arrives zeroed and most of it should stay untouched, so there's nothing to do but say so. */
void tr_web_status_init(tr_web_status *out)
{
	out->version = 1;
}

/* Blip's talking speed, in characters. A long answer speeds up rather than taking minutes, and it stops for breath
 * where someone reading it aloud would. */
static const double REVEAL_PER_S = 45.0, REVEAL_PER_S_PER_ROW_LEFT = 2.0;
static const double PAUSE_SENTENCE = 9.0, PAUSE_CLAUSE = 4.0, PAUSE_PARAGRAPH = 7.0;
static const double TALK_TAIL_S = 0.25;

int web_content_y(int tab)
{
	return tab == TR_WEB_CHAT ? ORB_Y1 : ADDR_Y1;
}

/* ---- webd's frames ---- */

static void copy_text(char *dst, size_t cap, const uint8_t *src, size_t n)
{
	size_t o = 0;
	for (size_t i = 0; i < n && o + 1 < cap; i++)
		if (src[i] >= 0x20 && src[i] != 0x7f)
			dst[o++] = (char)src[i];
	dst[o] = '\0';
}

static void apply_frame(tr_web_status *st, web_doc *d, int kind, const uint8_t *p, size_t n)
{
	switch (kind) {
	case WEB_F_RESET:
		d->n_rows = 0;
		break;
	case WEB_F_ROW: {
		if (n < 2)
			return;
		const int i = p[0] | p[1] << 8;
		if (i >= WEB_MAX_ROWS)
			return;
		const size_t len = n - 2 > WEB_ROW_BYTES ? WEB_ROW_BYTES : n - 2;
		web_row *r = &d->rows[i];
		r->len = (uint8_t)len;
		memcpy(r->b, p + 2, len);
		/* Rows jumped over must not show what an older page left there. */
		for (int k = d->n_rows; k < i; k++)
			d->rows[k].len = 0;
		if (i >= d->n_rows)
			d->n_rows = i + 1;
		break;
	}
	case WEB_F_ROWS: {
		if (n < 2)
			return;
		const int count = p[0] | p[1] << 8;
		if (count < d->n_rows)
			d->n_rows = count;
		break;
	}
	case WEB_F_ADDR:
		if (n < 1)
			return;
		d->secure = p[0] != 0;
		copy_text(d->addr, sizeof(d->addr), p + 1, n - 1);
		break;
	case WEB_F_STATUS:
		if (n < 1)
			return;
		d->state = p[0] <= WEB_BUSY ? p[0] : WEB_IDLE;
		copy_text(d->status, sizeof(d->status), p + 1, n - 1);
		break;
	case WEB_F_SCROLL:
		if (n < 4)
			return;
		d->scroll_to = (unsigned)p[0] | (unsigned)p[1] << 8 | (unsigned)p[2] << 16 | (unsigned)p[3] << 24;
		d->scroll_seq++;
		break;
	case WEB_F_OPEN:
		copy_text(st->open_url, sizeof(st->open_url), p, n);
		break;
	default:
		break;
	}
	st->version++;
}

void tr_web_feed(tr_web_status *st, int which, const uint8_t *data, size_t n)
{
	if (which < 0 || which >= WEB_SLOTS)
		return;
	web_doc *d = &st->docs[which];
	size_t i = 0;
	while (i < n) {
		if (d->head_n < 4) {
			d->head[d->head_n++] = data[i++];
			if (d->head_n == 4) {
				d->want = (size_t)d->head[1] | (size_t)d->head[2] << 8 | (size_t)d->head[3] << 16;
				d->have = 0;
			}
		}
		if (d->head_n < 4)
			continue;
		const size_t take = n - i < d->want - d->have ? n - i : d->want - d->have;
		if (d->have < WEB_FRAME_MAX) {          /* anything longer than a frame can be is dropped */
			const size_t room = WEB_FRAME_MAX - d->have;
			memcpy(d->frame + d->have, data + i, take < room ? take : room);
		}
		d->have += take;
		i += take;
		if (d->have == d->want) {
			if (d->want <= WEB_FRAME_MAX)
				apply_frame(st, d, d->head[0], d->frame, d->want);
			d->head_n = 0;
		}
	}
}

const char *tr_web_peek_open(const tr_web_status *st)
{
	return st->open_url;
}

void tr_web_clear_open(tr_web_status *st)
{
	st->open_url[0] = '\0';
}

const char *tr_web_address(const tr_web_status *st)
{
	return st->docs[TR_WEB_PAGE].addr;
}

int tr_web_tab(const tr_web *s)
{
	return s->tab;
}

void tr_web_set_tab(tr_web *s, int tab)
{
	s->tab = tab == TR_WEB_PAGE ? TR_WEB_PAGE : TR_WEB_CHAT;
	s->velocity = 0.0;
}

int tr_web_scroll_of(const tr_web *s, int tab)
{
	return tab == TR_WEB_PAGE ? (int)s->scroll[TR_WEB_PAGE] : (int)s->scroll[TR_WEB_CHAT];
}

void tr_web_set_compose(tr_web *s, const char *text, const char *label)
{
	s->composing = text != NULL;
	snprintf(s->compose, sizeof(s->compose), "%s", text ? text : "");
	snprintf(s->compose_label, sizeof(s->compose_label), "%s", label ? label : "");
	s->compose_version++;
}

/* ---- scrolling ---- */

static double max_scroll(const tr_web *s, const tr_web_status *st, int tab)
{
	const double total = (double)web_rows_showing(s, st, tab) * WEB_ROW_H;
	const double view = CONTENT_Y1 - web_content_y(tab);
	return total > view ? total - view : 0.0;
}

static double clamp_scroll(double v, double max)
{
	return v < 0.0 ? 0.0 : v > max ? max : v;
}

/* ---- writing out the chat ---- */

/* The user's own words, errors and notes such as "searching" aren't Blip talking, so they're just there. */
static int is_said(const web_row *r)
{
	if (!r->len || r->b[0] == WEB_ART_MARK)
		return 0;
	return r->b[0] != WEB_S_USER && r->b[0] != WEB_S_ERROR && r->b[0] != WEB_S_DIM;
}

/* The character in cell i of a row and how many cells it has: the bytes are from webd, so lengths are checked. */
static int row_cells(const web_row *r, int want, int *ch)
{
	int cells = 0;
	for (int i = 0; i < r->len; i++) {
		const uint8_t c = r->b[i];
		if (c == WEB_C_LINK || c == WEB_C_FIELD) {
			i += 2;
		} else if (c >= 0x20) {
			if (ch && cells == want)
				*ch = c;
			cells++;
		}
	}
	return cells;
}

int web_rows_showing(const tr_web *s, const tr_web_status *st, int tab)
{
	const web_doc *d = &st->docs[tab];
	if (tab != TR_WEB_CHAT || !d->n_rows)
		return d->n_rows;
	const int last = tr_min(s->reveal_row, d->n_rows - 1);
	return last + (s->reveal_cells > 0 || !is_said(&d->rows[last]));
}

int web_cells_showing(const tr_web *s, const web_doc *d, int tab, int i)
{
	if (tab != TR_WEB_CHAT || i < s->reveal_row || !is_said(&d->rows[i]))
		return INT_MAX;
	return i == s->reveal_row ? s->reveal_cells : 0;
}

static int still_to_say(const tr_web *s, const web_doc *d)
{
	if (s->reveal_row < d->n_rows - 1)
		return 1;
	return d->n_rows && is_said(&d->rows[d->n_rows - 1]) && s->reveal_cells < row_cells(&d->rows[d->n_rows - 1], -1, NULL);
}

static double pause_after(const web_row *r, int cell)
{
	int ch = 0, next = ' ';
	row_cells(r, cell, &ch);
	row_cells(r, cell + 1, &next);
	if (next != ' ')
		return 0.0;                /* the point in 3.5 isn't the end of anything */
	if (ch == '.' || ch == '!' || ch == '?')
		return PAUSE_SENTENCE;
	return ch == ',' || ch == ':' || ch == ';' ? PAUSE_CLAUSE : 0.0;
}

static void reveal_advance(tr_web *s, const web_doc *d, double dt)
{
	const int last = d->n_rows - 1;
	if (last < 0) {
		s->reveal_row = s->reveal_cells = 0;
		s->reveal_budget = 0.0;
		return;
	}
	if (s->reveal_row > last) {
		s->reveal_row = last;
		s->reveal_cells = 0;
	}
	/* If the user asks something else part way through, Blip moves on to that. */
	for (int i = last; i > s->reveal_row; i--)
		if (d->rows[i].len && d->rows[i].b[0] == WEB_S_USER) {
			s->reveal_row = i;
			s->reveal_cells = 0;
			break;
		}
	s->reveal_budget += dt * (REVEAL_PER_S + REVEAL_PER_S_PER_ROW_LEFT * (last - s->reveal_row));
	/* It stays on the last row when it gets there, because that row may yet grow. */
	for (;;) {
		const web_row *r = &d->rows[s->reveal_row];
		const int said = is_said(r), cells = row_cells(r, -1, NULL);
		if (said && s->reveal_cells < cells) {
			if (s->reveal_budget < 1.0)
				return;
			s->reveal_budget -= 1.0 + pause_after(r, s->reveal_cells);
			s->reveal_cells++;
		} else if (s->reveal_row < last) {
			if (!cells)
				s->reveal_budget -= PAUSE_PARAGRAPH;
			s->reveal_row++;
			s->reveal_cells = 0;
		} else {
			s->reveal_budget = 0.0;    /* caught up: nothing saved for the next sentence to burst out with */
			return;
		}
	}
}

static void follow_talk(tr_web *s, const tr_web_status *st, double now)
{
	const web_doc *d = &st->docs[TR_WEB_CHAT];
	const int replying = d->state == WEB_BUSY && !strcmp(d->status, WEB_REPLYING);
	if (replying || still_to_say(s, d))
		s->talk_until = now + TALK_TAIL_S;
	if (!d->n_rows)
		s->talk_until = 0.0;
}

uint64_t tr_web_advance(tr_web *s, const tr_web_status *st, double now)
{
	const double dt = s->last_advance > 0.0 && now > s->last_advance ? now - s->last_advance : 0.0;
	s->last_advance = now;
	for (int t = 0; t < WEB_SLOTS; t++)
		if (s->seen_scroll[t] != st->docs[t].scroll_seq) {
			s->seen_scroll[t] = st->docs[t].scroll_seq;
			s->scroll[t] = (double)st->docs[t].scroll_to;
			if (t == s->tab)
				s->velocity = 0.0;
		}
	if (!s->down && s->velocity != 0.0) {
		s->scroll[s->tab] += s->velocity * dt;
		s->velocity *= exp(-2.8 * dt);
		if (fabs(s->velocity) < 25.0)
			s->velocity = 0.0;
	}
	reveal_advance(s, &st->docs[TR_WEB_CHAT], dt);
	const double chat_max = max_scroll(s, st, TR_WEB_CHAT);
	if (s->follow && !(s->down && s->tab == TR_WEB_CHAT))
		s->scroll[TR_WEB_CHAT] = chat_max;
	s->scroll[TR_WEB_CHAT] = clamp_scroll(s->scroll[TR_WEB_CHAT], chat_max);
	s->scroll[TR_WEB_PAGE] = clamp_scroll(s->scroll[TR_WEB_PAGE], max_scroll(s, st, TR_WEB_PAGE));

	follow_talk(s, st, now);

	/* The mascot is always moving on the chat, and writing needs more frames than that to look like writing; the
	 * browser only needs its globe while loading. */
	const web_doc *d = &st->docs[s->tab];
	double fps = 0.0;
	if (s->tab == TR_WEB_CHAT)
		fps = still_to_say(s, d) ? 24.0 : d->state == WEB_BUSY || now < s->talk_until ? 15.0 : 5.0;
	else if (d->state == WEB_BUSY)
		fps = 20.0;
	const uint64_t tick = fps > 0.0 ? (uint64_t)(now * fps) : 0;
	return tick << 40 ^ (uint64_t)(int64_t)s->scroll[s->tab] << 16 ^ (uint64_t)st->version << 2 ^
	       (uint64_t)s->compose_version << 28 ^ (uint64_t)s->pressed << 56 ^ (uint64_t)s->tab;
}

/* ---- touches ---- */

static int key_count(const tr_web *s)
{
	return s->tab == TR_WEB_CHAT ? 1 : 3;
}

static int key_at(const tr_web *s, int x, int y)
{
	if (y >= KEYS_Y1)
		return -1;
	const int n = key_count(s);
	const int i = (KEYS_X1 - x) / KEY_W;
	return x <= KEYS_X1 && i < n ? n - 1 - i : -1;
}

static int press_at(const tr_web *s, int x, int y)
{
	if (y < TAB_Y1 && x >= TAB_CHAT_X0 && x < TAB_CHAT_X1)
		return PRESS_TAB_CHAT;
	if (y < TAB_Y1 && x >= TAB_PAGE_X0 && x < TAB_PAGE_X1)
		return PRESS_TAB_PAGE;
	const int key = key_at(s, x, y);
	if (key >= 0)
		return PRESS_KEY0 + key;
	if (y >= INPUT_Y0 - 4)
		return PRESS_INPUT;
	return PRESS_NONE;
}

/* What's in cell col of a row: writes the link or field there and returns its kind, or TR_WEB_NONE. */
static int run_at(const web_row *r, int col)
{
	if (r->len && r->b[0] == WEB_ART_MARK)
		return -1;
	int at = 0, run = -1, kind = TR_WEB_NONE;
	for (int i = 0; i < r->len; i++) {
		const uint8_t c = r->b[i];
		if (c == WEB_C_LINK || c == WEB_C_FIELD) {
			if (i + 2 >= r->len)
				return -1;
			run = r->b[i + 1] << 8 | r->b[i + 2];
			kind = c == WEB_C_LINK ? TR_WEB_LINK : TR_WEB_FIELD;
			i += 2;
		} else if (c == WEB_C_END) {
			run = -1;
		} else if (c >= 0x20) {
			if (at == col && run >= 0)
				return kind << 16 | run;
			at++;
		}
	}
	return -1;
}

static tr_web_cmd hit_content(const tr_web *s, const tr_web_status *st, int x, int y)
{
	const web_doc *d = &st->docs[s->tab];
	const int content_y = web_content_y(s->tab);
	const int col = (x - WEB_MARGIN) / WEB_ADVANCE;
	/* Fingers are wide: the exact cell first, then either side of it, then the rows above and below. */
	static const int DY[] = { 0, -8, 8 };
	static const int DX[] = { 0, -1, 1, -2, 2 };
	for (size_t j = 0; j < sizeof(DY) / sizeof(DY[0]); j++) {
		const int row = (y + DY[j] - content_y + (int)s->scroll[s->tab]) / WEB_ROW_H;
		if (y + DY[j] < content_y || row < 0 || row >= web_rows_showing(s, st, s->tab))
			continue;
		for (size_t i = 0; i < sizeof(DX) / sizeof(DX[0]); i++) {
			const int found = run_at(&d->rows[row], col + DX[i]);
			if (found >= 0)
				return (tr_web_cmd){ found >> 16, found & 0xffff };
		}
	}
	return (tr_web_cmd){ TR_WEB_NONE, 0 };
}

static tr_web_cmd key_command(const tr_web *s, const tr_web_status *st, int key)
{
	const int busy = st->docs[s->tab].state == WEB_BUSY;
	if (s->tab == TR_WEB_CHAT)
		return (tr_web_cmd){ busy ? TR_WEB_STOP_CHAT : TR_WEB_NEW_CHAT, 0 };
	if (key == 0)
		return (tr_web_cmd){ TR_WEB_BACK, 0 };
	if (key == 1)
		return (tr_web_cmd){ TR_WEB_FORWARD, 0 };
	return (tr_web_cmd){ busy ? TR_WEB_STOP_PAGE : TR_WEB_RELOAD, 0 };
}

tr_web_cmd tr_web_touch(const tr_web *in, tr_web *out, const tr_web_status *st, int event, int x, int y, double now)
{
	if (out != in)
		*out = *in;
	tr_web *s = out;
	tr_web_cmd cmd = { TR_WEB_NONE, 0 };
	const int in_content = y >= web_content_y(s->tab) && y < CONTENT_Y1;
	if (event == TR_WEB_DOWN) {
		s->down = 1;
		s->moved = 0;
		s->touch_x = x;
		s->touch_y = y;
		s->pressed = press_at(s, x, y);
		s->scroll_at_touch = s->scroll[s->tab];
		s->velocity = 0.0;
		s->touch_velocity = 0.0;
		s->last_y = y;
		s->last_t = now;
		if (!in_content && s->pressed == PRESS_NONE)
			s->down = 0;
	} else if (event == TR_WEB_MOVE && s->down) {
		const int dy = y - s->touch_y;
		if (dy > TAP_SLOP || dy < -TAP_SLOP || x - s->touch_x > TAP_SLOP || s->touch_x - x > TAP_SLOP)
			s->moved = 1;
		if (s->moved)
			s->pressed = PRESS_NONE;
		if (s->moved && s->touch_y >= web_content_y(s->tab) && s->touch_y < CONTENT_Y1) {
			const double max = max_scroll(s, st, s->tab);
			s->scroll[s->tab] = clamp_scroll(s->scroll_at_touch - dy, max);
			if (s->tab == TR_WEB_CHAT)
				s->follow = s->scroll[s->tab] >= max - 2.0;
			const double dt = now - s->last_t;
			if (dt > 0.005) {
				s->touch_velocity = 0.6 * ((s->last_y - y) / dt) + 0.4 * s->touch_velocity;
				s->last_y = y;
				s->last_t = now;
			}
		}
	} else if (event == TR_WEB_UP && s->down) {
		s->down = 0;
		const int press = s->pressed;
		s->pressed = PRESS_NONE;
		if (s->moved) {
			if (s->touch_y >= web_content_y(s->tab) && s->touch_y < CONTENT_Y1 && now - s->last_t < 0.1) {
				s->velocity = s->touch_velocity;
				if (s->tab == TR_WEB_CHAT && s->velocity < 0.0)
					s->follow = 0;
			}
		} else if (press == PRESS_TAB_CHAT) {
			tr_web_set_tab(s, TR_WEB_CHAT);
		} else if (press == PRESS_TAB_PAGE) {
			tr_web_set_tab(s, TR_WEB_PAGE);
		} else if (press == PRESS_INPUT) {
			cmd.kind = TR_WEB_INPUT;
		} else if (press >= PRESS_KEY0) {
			cmd = key_command(s, st, press - PRESS_KEY0);
			if (cmd.kind == TR_WEB_NEW_CHAT)
				s->follow = 1;
		} else if (in_content && s->tab == TR_WEB_CHAT && still_to_say(s, &st->docs[TR_WEB_CHAT])) {
			/* A tap finishes the sentence, and the rest, rather than following a link that's still going past. */
			s->reveal_row = st->docs[TR_WEB_CHAT].n_rows - 1;
			s->reveal_cells = row_cells(&st->docs[TR_WEB_CHAT].rows[s->reveal_row], -1, NULL);
		} else if (in_content) {
			cmd = hit_content(s, st, x, y);
		}
	}
	return cmd;
}
