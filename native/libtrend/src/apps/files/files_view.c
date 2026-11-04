/* Files drawing: a pure function from state, status and time to pixels. The whole app area is redrawn
 * each time, as Calculator does, and only while something on it has changed. */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "files_state.h"

#define RGB(r, g, b) ((tr_colour)(r) | (tr_colour)(g) << 8 | (tr_colour)(b) << 16 | 0xff000000u)

static const tr_colour BG = RGB(0, 0, 0);
static const tr_colour FRAME = RGB(0, 85, 48);
static const tr_colour PANEL = RGB(0, 7, 4), SCAN = RGB(0, 13, 7);
static const tr_colour DIM = RGB(0, 110, 62), TEXT = RGB(190, 245, 210);
static const tr_colour BAR_BG = RGB(0, 34, 20);
static const tr_colour STOP_FILL = RGB(14, 3, 3), STOP_EDGE = RGB(125, 42, 42), STOP_TEXT = RGB(255, 110, 110);

enum { TEXT_MAX = 128, SIZE_MAX_TEXT = 32 };

static inline float width_of(const tr_glyph *font, const char *s)
{
	return tr_text_width(font, (const uint8_t *)s, (int)strlen(s));
}

static inline void put_text(tr_surface dst, const tr_glyph *font, const char *s, int x, int y, tr_colour c)
{
	tr_draw_text(dst, font, (const uint8_t *)s, (int)strlen(s), (float)x, y, c);
}

/* src, cut short with an ellipsis if it's wider than max_w. */
static void put_fitted(tr_surface dst, const tr_glyph *font, const char *src, int x, int y, int max_w, tr_colour c)
{
	char line[TEXT_MAX];
	snprintf(line, sizeof(line), "%s", src);
	size_t n = strlen(line);
	while (n > 0 && width_of(font, line) > (float)max_w) {
		n--;
		line[n] = (char)TR_FILES_ELLIPSIS;
		line[n + 1] = '\0';
	}
	put_text(dst, font, line, x, y, c);
}

static void draw_card(tr_surface dst, const tr_files_theme *t, int y0, int y1, const char *label)
{
	tr_fill_round_rect(dst, (tr_rect){ y0, y1, CARD_X0, CARD_X1 }, 9, FRAME);
	tr_fill_round_rect(dst, (tr_rect){ y0 + 2, y1 - 2, CARD_X0 + 2, CARD_X1 - 2 }, 7, PANEL);
	tr_fill_stripes(dst, (tr_rect){ y0 + 4, y1 - 3, CARD_X0 + 3, CARD_X1 - 2 }, 3, SCAN);
	const int w = (int)width_of(t->font16, label);
	tr_fill_rect(dst, (tr_rect){ y0 - 2, y0 + 3, CARD_X0 + 18, CARD_X0 + 19 + w }, BG);
	put_text(dst, t->font16, label, CARD_X0 + 18, y0 - 10, DIM);
}

/* ---- the share card ---- */

static void draw_folder(tr_surface dst, const tr_files_theme *t, int spinning, double now)
{
	const float turn = spinning ? (float)fmod(now * 1.6, 6.283185307) : 0.45f;
	const float c = cosf(turn), s = sinf(turn), ct = cosf(0.22f), st = sinf(0.22f);
	const float r[9] = { c, 0.0f, s, st * s, ct, -st * c, -ct * s, st, ct * c };
	tr_mesh_draw(t->icon, r, t->view, t->atlas, dst, TR_FILES_ICON_X, TR_FILES_ICON_Y);
}

static void draw_share_on(tr_surface dst, const files_shown *sh, const tr_files_theme *t)
{
	const int x = CARD_X0 + 16;
	if (sh->address[0]) {
		char url[TEXT_MAX];
		if (sh->port == 80)
			snprintf(url, sizeof(url), "http://%s", sh->address);
		else
			snprintf(url, sizeof(url), "http://%s:%d", sh->address, sh->port);
		put_text(dst, t->font17, "Open this on a device on your Wi-Fi:", x, SHARE_Y0 + 16, DIM);
		put_fitted(dst, t->font25, url, x, SHARE_Y0 + 42, CARD_X1 - CARD_X0 - 32, TEXT);
	} else {
		put_text(dst, t->font17, "No network yet.", x, SHARE_Y0 + 16, t->error);
		put_text(dst, t->font17, "Connect to Wi-Fi in Settings.", x, SHARE_Y0 + 42, DIM);
	}
	put_text(dst, t->font17, "PIN", x, SHARE_Y0 + 96, DIM);
	char spaced[8] = "";
	if (strlen(sh->pin) == 6)
		snprintf(spaced, sizeof(spaced), "%.3s %.3s", sh->pin, sh->pin + 3);
	put_text(dst, t->font54, spaced, x, SHARE_Y0 + 118, t->accent);
	put_text(dst, t->font17, "Changes every time", x, SHARE_Y0 + 200, DIM);
	put_text(dst, t->font17, "you start sharing.", x, SHARE_Y0 + 224, DIM);
}

static void draw_share_off(tr_surface dst, const files_shown *sh, const tr_files_theme *t)
{
	const int x = CARD_X0 + 16;
	if (sh->phase == TR_FILES_STARTING) {
		put_text(dst, t->font25, "Starting...", x, SHARE_Y0 + 24, TEXT);
		return;
	}
	put_text(dst, t->font25, "Sharing is off", x, SHARE_Y0 + 24, TEXT);
	put_text(dst, t->font17, "Start it to add or fetch", x, SHARE_Y0 + 66, DIM);
	put_text(dst, t->font17, "files from a browser on", x, SHARE_Y0 + 90, DIM);
	put_text(dst, t->font17, "your Wi-Fi.", x, SHARE_Y0 + 114, DIM);
	if (sh->reason[0]) {
		put_text(dst, t->font17, "It stopped:", x, SHARE_Y0 + 170, t->error);
		put_fitted(dst, t->font17, sh->reason, x, SHARE_Y0 + 194, TR_FILES_ICON_X - x - 4, t->error);
	}
}

/* ---- the activity card ---- */

static void draw_row(tr_surface dst, const files_xfer *x, int y, const tr_files_theme *t)
{
	char done[SIZE_MAX_TEXT], total[SIZE_MAX_TEXT], right[SIZE_MAX_TEXT * 2 + 8];
	const int x0 = CARD_X0 + 16, x1 = CARD_X1 - 16;
	tr_files_format_size(x->done, done, sizeof(done));
	tr_files_format_size(x->total, total, sizeof(total));
	if (x->failed)
		snprintf(right, sizeof(right), "failed");
	else if (x->active)
		snprintf(right, sizeof(right), "%s / %s", done, total);
	else
		snprintf(right, sizeof(right), "%s", total);

	const int right_w = (int)width_of(t->font17, right);
	const char *dir = x->sending ? "down" : "up";
	put_text(dst, t->font17, dir, x0, y, DIM);
	put_fitted(dst, t->font17, x->name, x0 + 46, y, x1 - x0 - 46 - right_w - 10, x->failed ? t->error : TEXT);
	put_text(dst, t->font17, right, x1 - right_w, y, x->failed ? t->error : DIM);

	const tr_rect bar = { y + 26, y + 32, x0, x1 };
	tr_fill_rect(dst, bar, BAR_BG);
	if (x->failed)
		return;
	const double part = !x->active || x->total <= 0 ? 1.0 : (double)x->done / (double)x->total;
	const int fill = (int)((double)(x1 - x0) * (part > 1.0 ? 1.0 : part));
	tr_fill_rect(dst, (tr_rect){ bar.y0, bar.y1, x0, x0 + fill }, x->active ? t->accent : DIM);
}

static void draw_activity(tr_surface dst, const files_shown *sh, const tr_files_theme *t)
{
	draw_card(dst, t, ACTIVITY_Y0, ACTIVITY_Y1, " activity ");
	int y = ROWS_Y0;
	for (int i = 0; i < FILES_SLOTS; i++) {
		if (!sh->xfers[i].used)
			continue;
		draw_row(dst, &sh->xfers[i], y, t);
		y += ROW_H;
	}
	if (y == ROWS_Y0)
		put_text(dst, t->font17, "Nothing yet.", CARD_X0 + 16, ROWS_Y0, DIM);
}

/* ---- the key ---- */

static void draw_key(tr_surface dst, const files_shown *sh, int pressed, const tr_files_theme *t)
{
	const int stopping = sh->phase == TR_FILES_ON;
	tr_colour fill = stopping ? STOP_FILL : t->accent, edge = stopping ? STOP_EDGE : t->accent;
	tr_colour ink = stopping ? STOP_TEXT : BG;
	if (pressed) {
		fill = stopping ? STOP_TEXT : TEXT;
		ink = BG;
	}
	if (sh->phase == TR_FILES_STARTING) {
		fill = PANEL;
		edge = FRAME;
		ink = DIM;
	}
	tr_fill_round_rect(dst, (tr_rect){ KEY_Y0, KEY_Y1, KEY_X0, KEY_X1 }, 7, edge);
	tr_fill_round_rect(dst, (tr_rect){ KEY_Y0 + 2, KEY_Y1 - 2, KEY_X0 + 2, KEY_X1 - 2 }, 5, fill);
	const char *label = stopping ? "stop sharing" : "start sharing";
	const int w = (int)width_of(t->font25, label);
	put_text(dst, t->font25, label, (KEY_X0 + KEY_X1 - w) / 2, (KEY_Y0 + KEY_Y1) / 2 - 15, ink);
}

void tr_files_render(const tr_files *s, const tr_files_status *st, const tr_files_theme *t, double now, tr_surface dst)
{
	const files_shown *sh = &st->shown;
	int spinning = 0;
	for (int i = 0; i < FILES_SLOTS; i++)
		spinning |= sh->xfers[i].active;

	tr_fill_rect(dst, (tr_rect){ 0, dst.h, 0, dst.w }, BG);
	draw_card(dst, t, SHARE_Y0, SHARE_Y1, " share ");
	if (sh->phase == TR_FILES_ON)
		draw_share_on(dst, sh, t);
	else
		draw_share_off(dst, sh, t);
	draw_folder(dst, t, spinning, now);
	draw_activity(dst, sh, t);
	if (sh->free_bytes >= 0) {
		char size[SIZE_MAX_TEXT], line[SIZE_MAX_TEXT + 16];
		tr_files_format_size(sh->free_bytes, size, sizeof(size));
		snprintf(line, sizeof(line), "%s free", size);
		put_text(dst, t->font17, line, CARD_X0 + 16, FREE_Y, DIM);
	}
	draw_key(dst, sh, s->pressed, t);
}
