/* Music drawing: a pure function from state and status to pixels. The whole app area is redrawn
 * each time, as Calculator does. */
#include <stdio.h>
#include <string.h>

#include "music_state.h"

#define RGB(r, g, b) ((tr_colour)(r) | (tr_colour)(g) << 8 | (tr_colour)(b) << 16 | 0xff000000u)

static const tr_colour BG = RGB(0, 0, 0);
static const tr_colour FRAME = RGB(0, 85, 48);
static const tr_colour PANEL = RGB(0, 7, 4), SCAN = RGB(0, 13, 7);
static const tr_colour DIM = RGB(0, 110, 62), MID = RGB(0, 150, 85), TEXT = RGB(190, 245, 210);
static const tr_colour KEY_FILL = RGB(0, 14, 8), SCOPE_BG = RGB(0, 3, 2), SCOPE_AXIS = RGB(0, 40, 24);
static const tr_colour ROW_LIT = RGB(0, 34, 20);

enum { TEXT_MAX = TR_MUSIC_NAME + 4 };

static inline float width_of(const tr_glyph *font, const char *s)
{
	return tr_text_width(font, (const uint8_t *)s, (int)strlen(s));
}

static inline void put_text(tr_surface dst, const tr_glyph *font, const char *s, int x, int y, tr_colour c)
{
	tr_draw_text(dst, font, (const uint8_t *)s, (int)strlen(s), (float)x, y, c);
}

/* src, cut short with an ellipsis if it's wider than max_w. */
static void fit_text(const tr_glyph *font, const char *src, float max_w, char *out, size_t cap)
{
	snprintf(out, cap, "%s", src);
	size_t n = strlen(out);
	if (width_of(font, out) <= max_w)
		return;
	while (n > 0 && n + 2 <= cap) {
		out[--n] = (char)TR_MUSIC_ELLIPSIS;
		out[n + 1] = '\0';
		if (width_of(font, out) <= max_w)
			return;
	}
	out[0] = '\0';
}

static void put_fitted(tr_surface dst, const tr_glyph *font, const char *s, int x, int y, int max_w, tr_colour c)
{
	char line[TEXT_MAX];
	fit_text(font, s, (float)max_w, line, sizeof(line));
	put_text(dst, font, line, x, y, c);
}

static void format_time(double seconds, char *out, size_t cap)
{
	const int t = seconds > 0.0 ? (int)seconds : 0;
	snprintf(out, cap, "%d:%02d", (t / 60) % 1000, t % 60);
}

static void draw_card(tr_surface dst, const tr_music_theme *t, int y0, int y1, const char *label)
{
	tr_fill_round_rect(dst, (tr_rect){ y0, y1, CARD_X0, CARD_X1 }, 9, FRAME);
	tr_fill_round_rect(dst, (tr_rect){ y0 + 2, y1 - 2, CARD_X0 + 2, CARD_X1 - 2 }, 7, PANEL);
	tr_fill_stripes(dst, (tr_rect){ y0 + 4, y1 - 3, CARD_X0 + 3, CARD_X1 - 2 }, 3, SCAN);
	const int w = (int)width_of(t->font16, label);
	tr_fill_rect(dst, (tr_rect){ y0 - 2, y0 + 3, CARD_X0 + 18, CARD_X0 + 19 + w }, BG);
	put_text(dst, t->font16, label, CARD_X0 + 18, y0 - 10, DIM);
}

/* ---- the now-playing card ---- */

static void draw_scope(tr_surface dst, const tr_music_status *st, tr_colour accent)
{
	const int x1 = SCOPE_X + TR_MUSIC_SCOPE * SCOPE_STEP;
	const int mid = (SCOPE_Y0 + SCOPE_Y1) / 2, half = (SCOPE_Y1 - SCOPE_Y0) / 2 - 2;
	tr_fill_rect(dst, (tr_rect){ SCOPE_Y0, SCOPE_Y1, SCOPE_X, x1 }, SCOPE_BG);
	tr_fill_rect(dst, (tr_rect){ mid, mid + 1, SCOPE_X, x1 }, SCOPE_AXIS);
	if (st->state != TR_PLAYER_PLAYING)
		return;
	int prev = mid - st->scope[0] * half / 32768;
	for (int i = 0; i < TR_MUSIC_SCOPE; i++) {
		const int y = mid - st->scope[i] * half / 32768;
		const int x = SCOPE_X + i * SCOPE_STEP;
		tr_fill_rect(dst, (tr_rect){ tr_min(prev, y), tr_max(prev, y) + 1, x, x + SCOPE_STEP }, accent);
		prev = y;
	}
}

static void draw_progress(tr_surface dst, const tr_music *s, const tr_music_status *st, const tr_music_theme *t)
{
	const int span = BAR_X1 - BAR_X0;
	double fraction = st->duration > 0.0 ? st->position / st->duration : 0.0;
	if (s->drag == DRAG_SEEK)
		fraction = (double)(s->seek_x - BAR_X0) / span;
	const int x = BAR_X0 + tr_clamp((int)(fraction * span), 0, span);
	tr_fill_rect(dst, (tr_rect){ BAR_Y0, BAR_Y1, BAR_X0, BAR_X1 }, SCOPE_BG);
	tr_fill_rect(dst, (tr_rect){ BAR_Y0, BAR_Y1, BAR_X0, x }, MID);
	tr_stroke_rect(dst, (tr_rect){ BAR_Y0, BAR_Y1, BAR_X0, BAR_X1 }, FRAME);
	if (st->duration > 0.0)
		tr_fill_rect(dst, (tr_rect){ BAR_Y0 - 3, BAR_Y1 + 3, x - 2, x + 2 }, t->accent);

	char now[16], total[16], line[40];
	format_time(s->drag == DRAG_SEEK ? fraction * st->duration : st->position, now, sizeof(now));
	format_time(st->duration, total, sizeof(total));
	snprintf(line, sizeof(line), "%s / %s", now, total);
	put_text(dst, t->font17, line, BAR_X0, TIME_Y, DIM);

	static const char *const OUTPUTS[] = { "SPEAKER", "HEADPHONES", "BLUETOOTH" };
	snprintf(line, sizeof(line), "%s  VOL %d", OUTPUTS[tr_clamp(st->output, 0, 2)], st->volume);
	put_text(dst, t->font17, line, BAR_X1 - (int)width_of(t->font17, line), TIME_Y, DIM);
}

/* A triangle pointing left (dir < 0) or right, h tall, with its flat side at x. */
static void draw_triangle(tr_surface dst, int x, int cy, int h, int dir, tr_colour c)
{
	for (int dy = -h / 2; dy <= h / 2; dy++) {
		const int len = (h / 2 - (dy < 0 ? -dy : dy)) * 4 / 5 + 1;
		const tr_rect r = dir > 0 ? (tr_rect){ cy + dy, cy + dy + 1, x, x + len }
					  : (tr_rect){ cy + dy, cy + dy + 1, x - len, x };
		tr_fill_rect(dst, r, c);
	}
}

static void draw_key_icon(tr_surface dst, int key, int playing, int cx, int cy, tr_colour c)
{
	enum { H = 30, HALF = H / 2, TRI = 12, BAR = 5 };
	if (key == KEY_PLAY && playing) {
		tr_fill_rect(dst, (tr_rect){ cy - HALF, cy + HALF, cx - 12, cx - 3 }, c);
		tr_fill_rect(dst, (tr_rect){ cy - HALF, cy + HALF, cx + 3, cx + 12 }, c);
	} else if (key == KEY_PLAY) {
		draw_triangle(dst, cx - TRI / 2, cy, H, 1, c);
	} else if (key == KEY_PREV) {
		tr_fill_rect(dst, (tr_rect){ cy - HALF, cy + HALF, cx - TRI, cx - TRI + BAR }, c);
		draw_triangle(dst, cx + TRI - 2, cy, H, -1, c);
	} else {
		draw_triangle(dst, cx - TRI + 2, cy, H, 1, c);
		tr_fill_rect(dst, (tr_rect){ cy - HALF, cy + HALF, cx + TRI - BAR, cx + TRI }, c);
	}
}

static void draw_keys(tr_surface dst, const tr_music *s, const tr_music_status *st, const tr_music_theme *t)
{
	for (int i = 0; i < N_KEYS; i++) {
		const int x0 = KEY_X0 + i * (KEY_W + KEY_GAP);
		const int held = s->pressed_key == i;
		tr_fill_round_rect(dst, (tr_rect){ KEY_Y0, KEY_Y1, x0, x0 + KEY_W }, 7, held ? t->accent : MID);
		tr_fill_round_rect(dst, (tr_rect){ KEY_Y0 + 2, KEY_Y1 - 2, x0 + 2, x0 + KEY_W - 2 }, 5, held ? t->accent : KEY_FILL);
		draw_key_icon(dst, i, st->state == TR_PLAYER_PLAYING, x0 + KEY_W / 2, (KEY_Y0 + KEY_Y1) / 2, held ? BG : t->accent);
	}
}

static void draw_now_playing(tr_surface dst, const tr_music *s, const tr_music_status *st, const tr_music_theme *t)
{
	draw_card(dst, t, NOW_Y0, NOW_Y1, " now playing ");
	const int max_w = BAR_X1 - BAR_X0;
	put_fitted(dst, t->font25, st->title[0] ? st->title : "Nothing playing", BAR_X0, TITLE_Y, max_w, st->title[0] ? t->accent : DIM);
	if (st->error[0])
		put_fitted(dst, t->font17, st->error, BAR_X0, ARTIST_Y, max_w, t->error);
	else
		put_fitted(dst, t->font17, st->artist, BAR_X0, ARTIST_Y, max_w, MID);
	draw_scope(dst, st, t->accent);
	draw_progress(dst, s, st, t);
	draw_keys(dst, s, st, t);
}

/* ---- the track list ---- */

static void draw_empty_list(tr_surface dst, const tr_music_theme *t)
{
	static const char *const LINES[] = {
		"No music yet.",
		"",
		"Copy files to /data/music over USB:",
		"scp song.mp3 root@192.168.42.129:/data/music/",
		"",
		"Then reopen this app.",
		"MP3, FLAC, Ogg, Opus and WAV all play.",
	};
	for (int i = 0; i < (int)(sizeof(LINES) / sizeof(LINES[0])); i++)
		put_text(dst, t->font17, LINES[i], ROWS_X0 + 10, ROWS_Y0 + 14 + i * 26, i == 0 ? TEXT : MID);
}

static void draw_rows(tr_surface dst, const tr_music *s, const tr_music_status *st, const tr_music_library *lib, const tr_music_theme *t)
{
	/* A surface limited to the list, so rows clip cleanly at its edges. */
	const tr_surface clip = { dst.px + (size_t)ROWS_Y0 * (size_t)dst.stride, dst.stride, dst.w, ROWS_Y1 - ROWS_Y0 };
	const int first = s->scroll / ROW_H;
	const int last = tr_min(lib->n - 1, (s->scroll + (ROWS_Y1 - ROWS_Y0)) / ROW_H);
	for (int i = first; i <= last; i++) {
		const int y = i * ROW_H - s->scroll;
		const int current = i == st->track;
		if (i == s->pressed_row || current)
			tr_fill_rect(clip, (tr_rect){ y + 1, y + ROW_H - 1, ROWS_X0, ROWS_X1 }, i == s->pressed_row ? FRAME : ROW_LIT);
		if (current)
			tr_fill_rect(clip, (tr_rect){ y + 1, y + ROW_H - 1, ROWS_X0, ROWS_X0 + 4 }, t->accent);
		put_fitted(clip, t->font22, lib->names[i], ROWS_X0 + 12, y + 9, ROWS_X1 - ROWS_X0 - 28, current ? t->accent : TEXT);
	}
}

static void draw_scrollbar(tr_surface dst, const tr_music *s, int n)
{
	const int view = ROWS_Y1 - ROWS_Y0, total = n * ROW_H;
	if (total <= view)
		return;
	const int h = tr_max(24, view * view / total);
	const int y = ROWS_Y0 + (view - h) * s->scroll / (total - view);
	tr_fill_rect(dst, (tr_rect){ y, y + h, ROWS_X1 - 3, ROWS_X1 }, DIM);
}

static void draw_list(tr_surface dst, const tr_music *s, const tr_music_status *st, const tr_music_library *lib, const tr_music_theme *t)
{
	char label[32];
	snprintf(label, sizeof(label), " library: %d ", lib->n);
	draw_card(dst, t, LIST_Y0, LIST_Y1, label);
	if (lib->n == 0) {
		draw_empty_list(dst, t);
		return;
	}
	draw_rows(dst, s, st, lib, t);
	draw_scrollbar(dst, s, lib->n);
}

void tr_music_render(const tr_music *s, const tr_music_status *status, const tr_music_library *library,
		     const tr_music_theme *theme, tr_surface dst)
{
	tr_fill_rect(dst, (tr_rect){ 0, dst.h, 0, dst.w }, BG);
	draw_now_playing(dst, s, status, theme);
	draw_list(dst, s, status, library, theme);
}
