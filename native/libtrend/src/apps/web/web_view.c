/* Web app drawing: a pure function from state, status and time to pixels. */
#include <math.h>
#include <string.h>

#include "web_state.h"

#define RGB(r, g, b) ((tr_colour)(r) | (tr_colour)(g) << 8 | (tr_colour)(b) << 16 | 0xff000000u)

static const tr_colour BG = RGB(0, 0, 0);
static const tr_colour FRAME = RGB(0, 85, 48);
static const tr_colour PANEL = RGB(0, 7, 4), SCAN = RGB(0, 13, 7);
static const tr_colour DIM = RGB(0, 120, 68), TEXT = RGB(190, 245, 210), BOLD = RGB(255, 255, 255);
static const tr_colour HEAD = RGB(255, 215, 50), LINK = RGB(50, 230, 230), BAR = RGB(0, 70, 40);

static inline void put_text(tr_surface dst, const tr_glyph *font, const char *s, int x, int y, tr_colour c)
{
	tr_draw_text(dst, font, (const uint8_t *)s, (int)strlen(s), (float)x, y, c);
}

static tr_colour style_colour(int style, const tr_web_theme *t)
{
	switch (style) {
	case WEB_S_HEAD: return HEAD;
	case WEB_S_BOLD: return BOLD;
	case WEB_S_DIM: return DIM;
	case WEB_S_USER: return t->accent;
	case WEB_S_ERROR: return t->error;
	default: return TEXT;
	}
}

/* ---- rows ---- */

static void draw_art_row(tr_surface dst, const web_row *r, const tr_web_theme *t, int y)
{
	int32_t grid[WEB_ART_COLS * WEB_ART_ROWS];
	const int cells = tr_min(r->len - 1, WEB_ART_COLS * WEB_ART_ROWS);
	memset(grid, 0, sizeof(grid));
	for (int i = 0; i < cells; i++)
		grid[i] = r->b[1 + i] < WEB_PALETTE * WEB_SHADES ? r->b[1 + i] : 0;
	tr_grid_blit(grid, WEB_ART_COLS, WEB_ART_ROWS, t->atlas, dst, 0, y);
}

/* The bytes are from webd, so every length is checked. */
static void draw_text_row(tr_surface dst, const web_row *r, const tr_web_theme *t, int y, int showing)
{
	tr_colour colour = TEXT;
	int run = 0, col = 0, i = 0;       /* run: 0 none, 1 link, 2 field */
	while (i < r->len) {
		const uint8_t c = r->b[i];
		if (c >= WEB_S_NORMAL && c <= WEB_S_ERROR) {
			colour = style_colour(c, t);
			i++;
		} else if (c == WEB_C_LINK || c == WEB_C_FIELD) {
			run = c == WEB_C_LINK ? 1 : 2;
			i += 3;
			if (run == 2) {
				int width = 0;
				for (int k = i; k < r->len && r->b[k] != WEB_C_END; k++)
					width += r->b[k] >= 0x20;
				const int x0 = WEB_MARGIN + col * WEB_ADVANCE;
				tr_stroke_rect(dst, (tr_rect){ y, y + WEB_ROW_H - 1, x0 - 4, x0 + width * WEB_ADVANCE + 4 }, DIM);
			}
		} else if (c == WEB_C_END) {
			run = 0;
			i++;
		} else if (c < 0x20) {
			i++;
		} else {
			int end = i;
			while (end < r->len && r->b[end] >= 0x20)
				end++;
			const int n = tr_min(end - i, showing - col), x = WEB_MARGIN + col * WEB_ADVANCE;
			if (n <= 0)
				return;
			tr_draw_text(dst, t->font19, r->b + i, n, (float)x, y - 1, run == 1 ? LINK : run == 2 ? TEXT : colour);
			if (run == 1)
				tr_fill_rect(dst, (tr_rect){ y + WEB_ROW_H - 3, y + WEB_ROW_H - 2, x, x + n * WEB_ADVANCE }, LINK);
			col += n;
			i = end;
		}
	}
}

static void draw_rows(tr_surface dst, const tr_web *s, const tr_web_status *st, const tr_web_theme *t, int y0, int y1)
{
	const web_doc *d = &st->docs[s->tab];
	const int scroll = (int)s->scroll[s->tab], rows = web_rows_showing(s, st, s->tab);
	tr_surface view = { dst.px + (size_t)y0 * (size_t)dst.stride, dst.stride, dst.w, y1 - y0 };
	const int first = scroll / WEB_ROW_H;
	const int last = tr_min(rows - 1, (scroll + view.h) / WEB_ROW_H);
	for (int i = first; i <= last; i++) {
		const web_row *r = &d->rows[i];
		const int y = i * WEB_ROW_H - scroll;
		if (r->len && r->b[0] == WEB_ART_MARK)
			draw_art_row(view, r, t, y);
		else
			draw_text_row(view, r, t, y, web_cells_showing(s, d, s->tab, i));
	}
	const int total = rows * WEB_ROW_H;
	if (total > view.h) {
		const int h = tr_max(24, view.h * view.h / total);
		const int ty = (view.h - h) * scroll / (total - view.h);
		tr_fill_rect(view, (tr_rect){ ty, ty + h, dst.w - 4, dst.w - 1 }, BAR);
	}
}

/* ---- the globe and the mascot ---- */

/* Turned about the upright, then tipped towards the viewer, then rolled. */
static void draw_turned(tr_surface dst, const tr_web_theme *t, tr_mesh mesh, tr_view view, int x, int y, double yaw, double tilt, double roll)
{
	const float c = cosf((float)fmod(yaw, 6.283185307)), s = sinf((float)fmod(yaw, 6.283185307));
	const float ct = cosf((float)tilt), st = sinf((float)tilt), cr = cosf((float)roll), sr = sinf((float)roll);
	const float m[9] = { c, 0.0f, s, st * s, ct, -st * c, -ct * s, st, ct * c };
	const float r[9] = {
		cr * m[0] - sr * m[3], cr * m[1] - sr * m[4], cr * m[2] - sr * m[5],
		sr * m[0] + cr * m[3], sr * m[1] + cr * m[4], sr * m[2] + cr * m[5],
		m[6], m[7], m[8],
	};
	tr_mesh_draw(mesh, r, view, t->atlas, dst, x, y);
}

static void draw_globe(tr_surface dst, const tr_web_theme *t, tr_view view, int x, int y, double angle)
{
	draw_turned(dst, t, t->globe, view, x, y, angle, 0.32, 0.0);
}

/* Slow while idle, fast while there's work on. Whole turns of an idle spin mustn't jump when it speeds up, but a
 * jump is all it would be, so the angle just comes from the clock. */
static double spin(int busy, double now)
{
	return now * (busy ? 3.2 : 0.6);
}

typedef enum { MOOD_IDLE, MOOD_THINK, MOOD_TALK, MOOD_HELLO } web_mood;

static web_mood mood_of(const tr_web *s, const web_doc *d, double now)
{
	if (now < s->talk_until)
		return MOOD_TALK;
	if (d->state == WEB_BUSY)
		return MOOD_THINK;
	return d->n_rows ? MOOD_IDLE : MOOD_HELLO;
}

/* Mouths don't open in a regular beat when people talk, so this one opens and closes through a little pattern. */
static int talking_pose(double now)
{
	static const uint8_t PATTERN[] = {
		TR_WEB_MASCOT_TALK, TR_WEB_MASCOT_TALK_MID, TR_WEB_MASCOT_TALK_WIDE, TR_WEB_MASCOT_TALK_MID, TR_WEB_MASCOT_TALK,
		TR_WEB_MASCOT_IDLE, TR_WEB_MASCOT_TALK_MID, TR_WEB_MASCOT_TALK, TR_WEB_MASCOT_IDLE, TR_WEB_MASCOT_TALK,
		TR_WEB_MASCOT_TALK_MID, TR_WEB_MASCOT_TALK_WIDE, TR_WEB_MASCOT_TALK_WIDE, TR_WEB_MASCOT_TALK_MID, TR_WEB_MASCOT_IDLE,
	};
	return PATTERN[(size_t)(now * 13.0) % (sizeof(PATTERN) / sizeof(PATTERN[0]))];
}

static int mascot_pose(web_mood mood, double now)
{
	const int blinking = fmod(now, 4.3) < 0.22;
	switch (mood) {
	case MOOD_TALK:
		return talking_pose(now);
	case MOOD_THINK:
		return blinking ? TR_WEB_MASCOT_BLINK : TR_WEB_MASCOT_THINK;
	case MOOD_HELLO:
		return blinking ? TR_WEB_MASCOT_BLINK : TR_WEB_MASCOT_HELLO;
	default:
		return blinking ? TR_WEB_MASCOT_BLINK : TR_WEB_MASCOT_IDLE;
	}
}

/* It moves its whole head: turning is what shows the shape, so it's never quite still. */
static void draw_mascot(tr_surface dst, const tr_web_theme *t, tr_view view, int x, int y, web_mood mood, double now)
{
	double yaw = 0.32 * sin(now * 0.9), tilt = 0.06 + 0.05 * sin(now * 0.6), roll = 0.04 * sin(now * 0.7), bob = 0.0;
	switch (mood) {
	case MOOD_TALK:
		yaw = 0.24 * sin(now * 1.9);
		tilt = 0.08 + 0.09 * fabs(sin(now * 4.5));
		roll = 0.06 * sin(now * 1.3);
		bob = 3.0 * fabs(sin(now * 4.5));
		break;
	case MOOD_THINK:
		yaw = 0.42 * sin(now * 1.3);
		tilt = -0.14;
		roll = 0.1 * sin(now * 0.9);
		break;
	case MOOD_HELLO:
		roll = fmod(now, 6.0) < 2.0 ? 0.2 * sin(now * 7.0) : roll;
		break;
	default:
		break;
	}
	draw_turned(dst, t, t->mascot[mascot_pose(mood, now)], view, x, y - (int)bob, yaw, tilt, roll);
}

static void centre_text(tr_surface dst, const tr_glyph *font, const char *s, int y, tr_colour c)
{
	const int w = (int)tr_text_width(font, (const uint8_t *)s, (int)strlen(s));
	put_text(dst, font, s, (dst.w - w) / 2, y, c);
}

/* ---- the bars ---- */

static void draw_key(tr_surface dst, const tr_web_theme *t, tr_rect r, const char *label, int lit, int pressed)
{
	const tr_colour edge = lit || pressed ? t->accent : FRAME;
	tr_fill_round_rect(dst, r, 6, edge);
	tr_fill_round_rect(dst, (tr_rect){ r.y0 + 2, r.y1 - 2, r.x0 + 2, r.x1 - 2 }, 4, pressed ? t->accent : lit ? RGB(0, 50, 30) : PANEL);
	const int w = (int)tr_text_width(t->font19, (const uint8_t *)label, (int)strlen(label));
	put_text(dst, t->font19, label, (r.x0 + r.x1 - w) / 2, (r.y0 + r.y1) / 2 - 13, pressed ? BG : lit ? t->accent : TEXT);
}

static void draw_tabs(tr_surface dst, const tr_web *s, const tr_web_status *st, const tr_web_theme *t)
{
	draw_key(dst, t, (tr_rect){ 4, TAB_Y1 - 2, TAB_CHAT_X0, TAB_CHAT_X1 }, "chat", s->tab == TR_WEB_CHAT, s->pressed == PRESS_TAB_CHAT);
	draw_key(dst, t, (tr_rect){ 4, TAB_Y1 - 2, TAB_PAGE_X0, TAB_PAGE_X1 }, "web", s->tab == TR_WEB_PAGE, s->pressed == PRESS_TAB_PAGE);
	const int busy = st->docs[s->tab].state == WEB_BUSY;
	const char *const chat_keys[] = { busy ? "stop" : "new" };
	const char *const page_keys[] = { "<", ">", busy ? "x" : "R" };
	const int n = s->tab == TR_WEB_CHAT ? 1 : 3;
	const char *const *labels = s->tab == TR_WEB_CHAT ? chat_keys : page_keys;
	for (int i = 0; i < n; i++) {
		const int x1 = KEYS_X1 - (n - 1 - i) * KEY_W;
		draw_key(dst, t, (tr_rect){ 4, KEYS_Y1 - 2, x1 - KEY_W + 4, x1 }, labels[i], 0, s->pressed == PRESS_KEY0 + i);
	}
}

/* What Blip says, in a bubble with its tail towards it. It's only ever short; anything longer than two lines (or
 * webd gone wrong) is cut. */
static void draw_bubble(tr_surface dst, const tr_web_theme *t, const char *text, tr_colour colour)
{
	enum { X0 = 234, X1 = 474, Y0 = ORB_Y0 + 30, Y1 = ORB_Y0 + 132, TAIL = 12, PER_LINE = 21 };
	const int mid = (Y0 + Y1) / 2;
	tr_fill_round_rect(dst, (tr_rect){ Y0, Y1, X0, X1 }, 10, t->accent);
	tr_fill_round_rect(dst, (tr_rect){ Y0 + 2, Y1 - 2, X0 + 2, X1 - 2 }, 8, PANEL);
	for (int i = 0; i < TAIL; i++) {
		const int half = TAIL - i;
		tr_fill_rect(dst, (tr_rect){ mid - half, mid + half, X0 - i, X0 - i + 1 }, t->accent);
		if (half > 2)
			tr_fill_rect(dst, (tr_rect){ mid - half + 2, mid + half - 2, X0 - i + 3, X0 - i + 4 }, PANEL);
	}
	put_text(dst, t->font19, "Blip", X0 + 14, Y0 + 6, t->accent);
	const int n = (int)strlen(text), first = tr_min(n, PER_LINE), second = tr_min(n - first, PER_LINE);
	tr_draw_text(dst, t->font19, (const uint8_t *)text, first, X0 + 14.0f, Y0 + 34, colour);
	if (second)
		tr_draw_text(dst, t->font19, (const uint8_t *)text + first, second, X0 + 14.0f, Y0 + 60, colour);
}

static void draw_chat_head(tr_surface dst, const tr_web *s, const web_doc *d, const tr_web_theme *t, double now)
{
	const web_mood mood = mood_of(s, d, now);
	const tr_view v = t->head_view;
	draw_mascot(dst, t, v, 4, ORB_Y0 + 2, mood, now);
	/* It can still be talking after the answer has all arrived, so it's still saying this. */
	const char *says = mood == MOOD_TALK ? WEB_REPLYING : d->status[0] ? d->status : "Ask me anything";
	draw_bubble(dst, t, says, mood == MOOD_IDLE ? DIM : TEXT);
	tr_fill_rect(dst, (tr_rect){ ORB_Y1 - 2, ORB_Y1 - 1, 0, dst.w }, FRAME);
}

/* A new chat: just Blip, large, saying hello. */
static void draw_chat_empty(tr_surface dst, const tr_web *s, const web_doc *d, const tr_web_theme *t, double now)
{
	const tr_view v = t->hello_view;
	const int w = v.cols * t->atlas.cw, h = v.rows * t->atlas.ch;
	const int y = ORB_Y0 + (CONTENT_Y1 - ORB_Y0 - h - 110) / 2;
	tr_fill_rect(dst, (tr_rect){ ORB_Y0, CONTENT_Y1, 0, dst.w }, BG);
	draw_mascot(dst, t, v, (dst.w - w) / 2, y, mood_of(s, d, now), now);
	centre_text(dst, t->font25, "Hi, I'm Blip!", y + h + 6, t->accent);
	centre_text(dst, t->font19, d->status[0] ? d->status : "Ask me anything", y + h + 44, TEXT);
	centre_text(dst, t->font19, "or type a web address to browse", y + h + 72, DIM);
}

static void draw_address(tr_surface dst, const web_doc *d, const tr_web_theme *t)
{
	const int x0 = 10;
	char line[WEB_ADDR_MAX + 8];
	const char *text = d->state != WEB_IDLE && d->status[0] ? d->status : d->addr;
	const tr_colour colour = d->state != WEB_IDLE ? TEXT : d->secure || !d->addr[0] ? DIM : t->error;
	size_t n = strlen(text);
	const size_t fit = WEB_COLS;
	if (n > fit) {
		memcpy(line, text, fit - 3);
		memcpy(line + fit - 3, "...", 4);
		text = line;
		n = fit;
	}
	put_text(dst, t->font19, text[0] ? text : "start page", x0, ADDR_Y0, colour);
	tr_fill_rect(dst, (tr_rect){ ADDR_Y1 - 2, ADDR_Y1 - 1, 0, dst.w }, FRAME);
}

static void draw_input(tr_surface dst, const tr_web *s, const tr_web_theme *t)
{
	const int pressed = s->pressed == PRESS_INPUT;
	tr_fill_round_rect(dst, (tr_rect){ INPUT_Y0, INPUT_Y1, INPUT_X0, INPUT_X1 }, 8, pressed ? t->accent : FRAME);
	tr_fill_round_rect(dst, (tr_rect){ INPUT_Y0 + 2, INPUT_Y1 - 2, INPUT_X0 + 2, INPUT_X1 - 2 }, 6, PANEL);
	put_text(dst, t->font19, s->tab == TR_WEB_CHAT ? "> ask, or type a web address_" : "> web address, or ask the agent_",
	         INPUT_X0 + 14, INPUT_Y0 + 14, DIM);
}

/* What's being typed, wrapped, with its last lines in view. */
static void draw_compose(tr_surface dst, const tr_web *s, const tr_web_theme *t)
{
	enum { LINES = 4, LINE_H = 24 };
	tr_fill_round_rect(dst, (tr_rect){ COMPOSE_Y0, COMPOSE_Y1, 8, dst.w - 8 }, 8, t->accent);
	tr_fill_round_rect(dst, (tr_rect){ COMPOSE_Y0 + 2, COMPOSE_Y1 - 2, 10, dst.w - 10 }, 6, PANEL);
	put_text(dst, t->font16, s->compose_label, 20, COMPOSE_Y0 + 2, DIM);
	const int per_line = WEB_COLS - 2;
	const int n = (int)strlen(s->compose);
	const int first_line = tr_max(0, (n + 1) / per_line - (LINES - 1));
	for (int l = 0; l < LINES; l++) {
		const int at = (first_line + l) * per_line;
		if (at > n)
			break;
		const int len = tr_min(per_line, n - at);
		const int y = COMPOSE_Y0 + 20 + l * LINE_H;
		tr_draw_text(dst, t->font19, (const uint8_t *)s->compose + at, len, 20.0f, y, TEXT);
		if (at + per_line > n)
			tr_fill_rect(dst, (tr_rect){ y + 3, y + 22, 20 + len * WEB_ADVANCE, 20 + len * WEB_ADVANCE + 9 }, t->accent);
	}
}

/* A page on its way: the globe large in the middle. */
static void draw_big_globe(tr_surface dst, const tr_web_theme *t, int y0, int y1, const char *line1, const char *line2, tr_colour c1, double now, int busy)
{
	const int w = t->big_view.cols * t->atlas.cw, h = t->big_view.rows * t->atlas.ch;
	const int y = y0 + (y1 - y0 - h - 70) / 2;
	tr_fill_rect(dst, (tr_rect){ y - 8, y + h + 66, 0, dst.w }, BG);
	draw_globe(dst, t, t->big_view, (dst.w - w) / 2, y, spin(busy, now));
	if (line1)
		centre_text(dst, t->font25, line1, y + h + 2, c1);
	if (line2)
		centre_text(dst, t->font19, line2, y + h + 36, DIM);
}

void tr_web_render(const tr_web *s, const tr_web_status *st, const tr_web_theme *t, double now, tr_surface dst)
{
	const web_doc *d = &st->docs[s->tab];
	const int y0 = web_content_y(s->tab);
	const int busy = d->state == WEB_BUSY;
	tr_fill_rect(dst, (tr_rect){ 0, dst.h, 0, dst.w }, BG);
	tr_fill_stripes(dst, (tr_rect){ y0, CONTENT_Y1, 0, dst.w }, 3, SCAN);
	draw_rows(dst, s, st, t, y0, CONTENT_Y1);
	draw_tabs(dst, s, st, t);
	if (s->tab == TR_WEB_CHAT) {
		if (d->n_rows || s->composing)
			draw_chat_head(dst, s, d, t, now);
		else
			draw_chat_empty(dst, s, d, t, now);
	} else {
		draw_address(dst, d, t);
		if (busy)
			draw_big_globe(dst, t, y0, CONTENT_Y1, d->status, NULL, TEXT, now, 1);
	}
	draw_input(dst, s, t);
	if (s->composing)
		draw_compose(dst, s, t);
}
