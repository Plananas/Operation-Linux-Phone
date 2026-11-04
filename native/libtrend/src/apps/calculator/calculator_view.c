/* Calculator drawing: a pure function from state and time to pixels. The whole app area is redrawn
 * each time, and that's cheap enough that nothing needs caching. */
#include <math.h>
#include <string.h>

#include "calculator_state.h"

#define RGB(r, g, b) ((tr_colour)(r) | (tr_colour)(g) << 8 | (tr_colour)(b) << 16 | 0xff000000u)

static const tr_colour BG = RGB(0, 0, 0);
static const tr_colour FRAME = RGB(0, 85, 48), FRAME_HI = RGB(0, 150, 85);
static const tr_colour PANEL = RGB(0, 7, 4), SCAN = RGB(0, 13, 7);
static const tr_colour HIST = RGB(0, 110, 62), PREVIEW = RGB(0, 120, 68), DONE_EXPR = RGB(0, 150, 85);
static const tr_colour FLARE = RGB(200, 255, 225);

/* Key styles. */
typedef struct { tr_colour fill, edge, text, lit; } key_style;

/* Timings shared with calculator.c. */
#define TYPE_T 0.18
#define SCROLL_T 0.20
#define SHAKE_T 0.35
#define DECODE_STEP 0.03
#define DECODE_CHAR 0.16
#define CLEAR_STEP 0.018
#define CLEAR_CHAR 0.16
#define FADE_LEVELS 5

enum { HIST_Y = 30, HIST_DY = 24, EXPR_Y = 82, RES_Y = 122, GLOW_PAD = 10, GLOW_SCALE = 6 };

static inline double clamp01(double t)
{
	return t < 0.0 ? 0.0 : t > 1.0 ? 1.0 : t;
}

static inline unsigned mix_channel(unsigned a, unsigned b, double t)
{
	return (unsigned)((double)a + ((double)b - (double)a) * t);
}

static tr_colour mix(tr_colour a, tr_colour b, double t)
{
	const double k = clamp01(t);
	return mix_channel(a & 0xff, b & 0xff, k) |
	       mix_channel(a >> 8 & 0xff, b >> 8 & 0xff, k) << 8 |
	       mix_channel(a >> 16 & 0xff, b >> 16 & 0xff, k) << 16 | 0xff000000u;
}

static const tr_glyph *font_of(const tr_calc_theme *t, int size)
{
	return size == 54 ? t->font54 : t->font34;
}

static inline float width_of(const tr_glyph *font, const char *s)
{
	return tr_text_width(font, (const uint8_t *)s, (int)strlen(s));
}

static inline float put_text(tr_surface dst, const tr_glyph *font, const char *s, double x, int y, tr_colour c)
{
	return tr_draw_text(dst, font, (const uint8_t *)s, (int)strlen(s), (float)x, y, c);
}

/* ---- keys ---- */

static key_style style_of(unsigned key, tr_colour accent)
{
	switch (key) {
	case '=':
		return (key_style){ accent, accent, RGB(0, 0, 0), FLARE };
	case TR_CALC_DIV: case TR_CALC_MUL: case TR_CALC_MINUS: case '+': case '(': case ')':
		return (key_style){ RGB(0, 14, 8), RGB(0, 150, 85), accent, accent };
	case 'C': case TR_CALC_DEL:
		return (key_style){ RGB(14, 3, 3), RGB(125, 42, 42), RGB(255, 110, 110), RGB(255, 110, 110) };
	default:
		return (key_style){ RGB(0, 10, 6), RGB(0, 72, 42), RGB(190, 245, 210), RGB(150, 230, 185) };
	}
}

/* level 0 = idle, 1 = held (inverse video); in between = fading back. */
static void draw_key(tr_surface dst, const tr_calc_theme *t, int index, double level)
{
	const unsigned key = CALC_KEYCODES[index];
	const int c = index % CALC_COLS, r = index / CALC_COLS;
	const int x0 = KEY_X + c * (KEY_W + KEY_GAP_X), y0 = KEY_Y + r * (KEY_H + KEY_GAP_Y);
	const int x1 = x0 + KEY_W, y1 = y0 + KEY_H;
	key_style st = style_of(key, t->accent);
	if (level > 0.0) {
		st.fill = mix(st.fill, st.lit, level);
		st.edge = mix(st.edge, st.lit, level);
		st.text = mix(st.text, key == '=' ? RGB(0, 60, 35) : RGB(0, 0, 0), sqrt(level));
	}
	tr_fill_round_rect(dst, (tr_rect){ y0, y1 + 1, x0, x1 + 1 }, 7, st.edge);
	tr_fill_round_rect(dst, (tr_rect){ y0 + 2, y1 - 1, x0 + 2, x1 - 1 }, 5, st.fill);
	if (level == 0.0 && key != '=')
		tr_fill_rect(dst, (tr_rect){ y1 - 5, y1 - 4, x0 + 8, x1 - 7 }, mix(st.fill, st.edge, 0.35));

	const char single[2] = { (char)key, '\0' };
	const char *label = key == TR_CALC_DEL ? "del" : single;
	const int is_single = label == single;
	const tr_glyph *font = is_single ? t->font32 : t->font22;
	const double x = floor(x0 + (KEY_W - (double)width_of(font, label)) / 2.0 + 0.5);
	put_text(dst, font, label, x, y0 + (KEY_H - (is_single ? 36 : 26)) / 2, st.text);
}

/* How lit a recently released key still is, as a pre-squared fade step (0 = not at all). */
static double fade_level(double released, double now)
{
	const double age = now - released;
	if (released < 0.0 || age >= CALC_FADE)
		return 0.0;
	const double remaining = 1.0 - age / CALC_FADE;
	const int level = (int)ceil(FADE_LEVELS * remaining * remaining);
	return (double)(level < FADE_LEVELS - 1 ? level : FADE_LEVELS - 1) / FADE_LEVELS;
}

static void draw_keys(tr_surface dst, const tr_calc *s, const tr_calc_theme *t, double now)
{
	for (int i = 0; i < CALC_KEYS; i++)
		draw_key(dst, t, i, i == s->pressed ? 1.0 : fade_level(s->released[i], now));
}

/* ---- the display card ---- */

static void draw_card(tr_surface dst, const tr_calc_theme *t)
{
	static const char label[] = " calc ";
	tr_fill_round_rect(dst, (tr_rect){ DISP_Y0, DISP_Y1 + 1, DISP_X0, DISP_X1 + 1 }, 9, FRAME);
	tr_fill_round_rect(dst, (tr_rect){ DISP_Y0 + 2, DISP_Y1 - 1, DISP_X0 + 2, DISP_X1 - 1 }, 7, PANEL);
	tr_fill_stripes(dst, (tr_rect){ DISP_Y0 + 4, DISP_Y1 - 2, DISP_X0 + 3, DISP_X1 - 2 }, 3, SCAN);
	const int w = (int)width_of(t->font16, label);
	tr_fill_rect(dst, (tr_rect){ DISP_Y0 - 2, DISP_Y0 + 3, DISP_X0 + 18, DISP_X0 + 19 + w }, BG);
	put_text(dst, t->font16, label, DISP_X0 + 18, DISP_Y0 - 10, FRAME_HI);
}

/* ---- text effects ---- */

/* Characters build up through the shading ramp, left to right, then lock in. */
static void decode_text(const char *s, double t, const tr_calc_theme *th, char *out)
{
	const int ramp = th->n_shades - 1;
	const size_t n = strlen(s);
	for (size_t i = 0; i < n; i++) {
		const double p = (t - (double)i * DECODE_STEP) / DECODE_CHAR;
		out[i] = p >= 1.0 ? s[i] : p <= 0.0 ? ' ' : th->shades[1 + (int)(p * ramp) % ramp];
	}
	out[n] = '\0';
}

/* Characters fall back down the shading ramp, right to left, then vanish. */
static void dissolve_text(const char *s, double t, const tr_calc_theme *th, char *out)
{
	const int ramp = th->n_shades - 1;
	const size_t n = strlen(s);
	for (size_t i = 0; i < n; i++) {
		const double p = (t - (double)(n - 1 - i) * CLEAR_STEP) / CLEAR_CHAR;
		if (p <= 0.0 || s[i] == ' ') {
			out[i] = s[i];
		} else if (p >= 1.0) {
			out[i] = ' ';
		} else {
			const int shade = (int)((1.0 - p) * ramp);
			out[i] = th->shades[shade > 1 ? shade : 1];
		}
	}
	out[n] = '\0';
}

/* A phosphor bloom behind the result: its coverage at low level, blurred by shrinking it and
 * stretching it back with bilinear filtering. */
static void draw_glow(tr_surface dst, const tr_glyph *font, const char *text, int size, double x, int y, tr_colour c)
{
	const int w = tr_min((int)width_of(font, text) + 2 * GLOW_PAD, dst.w), h = size + 2 * GLOW_PAD;
	const int sw = tr_max(1, w / GLOW_SCALE), sh = tr_max(1, h / GLOW_SCALE);
	uint8_t mask[h][w];
	unsigned sum[sh][sw], count[sh][sw];
	memset(mask, 0, sizeof(mask));
	memset(sum, 0, sizeof(sum));
	memset(count, 0, sizeof(count));
	tr_mask_text(&mask[0][0], w, h, font, (const uint8_t *)text, (int)strlen(text), GLOW_PAD, GLOW_PAD, 95);

	for (int r = 0; r < h; r++)
		for (int k = 0; k < w; k++) {
			const int sr = r * sh / h, sk = k * sw / w;
			sum[sr][sk] += mask[r][k];
			count[sr][sk]++;
		}
	float small[sh][sw];
	for (int r = 0; r < sh; r++)
		for (int k = 0; k < sw; k++)
			small[r][k] = count[r][k] ? (float)sum[r][k] / (float)count[r][k] : 0.0f;

	for (int r = 0; r < h; r++) {
		const float fy = ((float)r + 0.5f) * (float)sh / (float)h - 0.5f;
		const int r0 = tr_clamp((int)floorf(fy), 0, sh - 1), r1 = tr_min(r0 + 1, sh - 1);
		const float wy = fy < 0.0f ? 0.0f : fy - (float)r0 > 1.0f ? 1.0f : fy - (float)r0;
		for (int k = 0; k < w; k++) {
			const float fx = ((float)k + 0.5f) * (float)sw / (float)w - 0.5f;
			const int k0 = tr_clamp((int)floorf(fx), 0, sw - 1), k1 = tr_min(k0 + 1, sw - 1);
			const float wx = fx < 0.0f ? 0.0f : fx - (float)k0 > 1.0f ? 1.0f : fx - (float)k0;
			const float top = small[r0][k0] * (1.0f - wx) + small[r0][k1] * wx;
			const float bottom = small[r1][k0] * (1.0f - wx) + small[r1][k1] * wx;
			mask[r][k] = (uint8_t)(top * (1.0f - wy) + bottom * wy + 0.5f);
		}
	}
	tr_fill_mask(dst, &mask[0][0], w, h, (int)x - GLOW_PAD, y - GLOW_PAD, c);
}

/* ---- history ---- */

/* History lines sit just above the prompt. A new line scrolls up from the prompt while the oldest
 * scrolls out through the top of the card, clipped there. */
static void draw_history(tr_surface dst, const tr_calc *s, const tr_calc_theme *t, double now, double right)
{
	const calc_hist_lines current = calc_hist_lines_of(s);
	const char *lines[CALC_HIST_LINES + 1];
	int n = 0;
	double age = now - s->t_scroll, off = 0.0;
	if (age >= 0.0 && age < SCROLL_T) {
		const double remaining = 1.0 - clamp01(age / SCROLL_T);
		off = HIST_DY * remaining * remaining * remaining;  /* ease out, cubic */
		if (s->scroll_from.n == 2)
			lines[n++] = s->scroll_from.line[0];
	} else {
		age = SCROLL_T;
	}
	for (int i = 0; i < current.n; i++)
		lines[n++] = current.line[i];

	const int clip = off > 0.0 ? DISP_Y0 + HIST_Y - 6 : 0;
	const tr_surface below = { dst.px + (size_t)clip * (size_t)dst.stride, dst.stride, dst.w, dst.h - clip };
	for (int i = 0; i < n; i++) {
		const int slot = 2 - n + i;        /* 1 = just above the prompt, -1 = leaving */
		const int y = (int)(DISP_Y0 + HIST_Y + slot * HIST_DY + off);
		tr_colour c = HIST;
		if (n == 3 && i == 0)
			c = mix(HIST, PANEL, age / SCROLL_T);
		else if (i == n - 1 && off > 0.0)
			c = mix(DONE_EXPR, HIST, age / SCROLL_T);
		put_text(below, t->font17, lines[i], right - (double)width_of(t->font17, lines[i]), y - clip, c);
	}
}

/* ---- prompt and result ---- */

static tr_colour tone_colour(calc_tone tone, const tr_calc_theme *t)
{
	return tone == TONE_ERROR ? t->error : tone == TONE_ACCENT ? t->accent : PREVIEW;
}

static inline int result_y(int size)
{
	return DISP_Y0 + RES_Y + (size == 54 ? 0 : 12);
}

/* "C": the old line dissolves down the shading ramp, right to left. */
static void draw_clearing(tr_surface dst, const tr_calc *s, const tr_calc_theme *t, double age, double right)
{
	const calc_lines *old = &s->cleared;
	const int tx = DISP_X0 + 18, ty = DISP_Y0 + EXPR_Y;
	char line[CALC_LINE_TEXT_MAX];
	dissolve_text(old->expr, age, t, line);
	const float pen = put_text(dst, t->font25, "> ", tx, ty, t->accent);
	put_text(dst, t->font25, line, pen, ty, mix(DONE_EXPR, FRAME, age / 0.3));
	if (old->text[0]) {
		const tr_glyph *font = font_of(t, old->size);
		dissolve_text(old->text, age, t, line);
		put_text(dst, font, line, right - (double)width_of(font, old->text), result_y(old->size),
		         mix(tone_colour(old->tone, t), FRAME, age / 0.3));
	}
}

/* "> expression": the newest character flares, with a blinking block cursor after it. */
static void draw_prompt(tr_surface dst, const tr_calc *s, const calc_lines *l, const tr_calc_theme *t, double now)
{
	const int tx = DISP_X0 + 18, ty = DISP_Y0 + EXPR_Y;
	char line[CALC_LINE_EXPR_MAX + 2];
	calc_copy(line, sizeof(line), "> ");
	calc_append(line, sizeof(line), l->expr);
	if (s->just_eq) {
		put_text(dst, t->font25, line, tx, ty, DONE_EXPR);
		return;
	}
	const double age = now - s->t_type;
	const int recent = age >= 0.0 && age < TYPE_T;
	float end;
	if (recent && l->expr[0]) {
		const size_t n = strlen(line);
		const char last[2] = { line[n - 1], '\0' };
		line[n - 1] = '\0';
		const float pen = put_text(dst, t->font25, line, tx, ty, t->accent);
		end = put_text(dst, t->font25, last, pen, ty, mix(FLARE, t->accent, age / TYPE_T));
	} else {
		end = put_text(dst, t->font25, line, tx, ty, t->accent);
	}
	if ((int)(now / CALC_BLINK) % 2 == 0 || recent) {
		const int cx = (int)end;
		tr_fill_rect(dst, (tr_rect){ ty + 3, ty + 30, cx + 3, cx + 15 }, t->accent);
	}
}

/* The live preview while typing; decoded and glowing after "="; an error shakes. */
static void draw_result(tr_surface dst, const tr_calc *s, const calc_lines *l, const tr_calc_theme *t, double now, double right)
{
	if (!l->text[0])
		return;
	const tr_glyph *font = font_of(t, l->size);
	const int y = result_y(l->size);
	double x = right - (double)width_of(font, l->text);
	char shown[CALC_LINE_TEXT_MAX];
	calc_copy(shown, sizeof(shown), l->text);
	tr_colour c = tone_colour(l->tone, t);
	const double since_eq = now - s->t_eq, since_err = now - s->t_err;

	if (s->just_eq && l->tone == TONE_ERROR && since_err >= 0.0 && since_err < SHAKE_T) {
		x += (int)(11.0 * sin(since_err * 60.0) * (1.0 - since_err / SHAKE_T));
	} else if (s->just_eq && since_eq >= 0.0) {
		const char *number = l->text + 2;
		const double done = DECODE_STEP * (double)strlen(number) + DECODE_CHAR;
		decode_text(number, since_eq, t, shown + 2);
		c = since_eq < done + 0.3 ? mix(FLARE, t->accent, (since_eq - done) / 0.3) : t->accent;
	}
	if (s->just_eq && l->tone != TONE_ERROR)
		draw_glow(dst, font, l->text, l->size, x, y, t->accent);
	put_text(dst, font, shown, x, y, c);
}

void tr_calc_render(const tr_calc *s, const tr_calc_theme *t, double now, tr_surface dst)
{
	const double right = DISP_X1 - 20;
	tr_fill_rect(dst, (tr_rect){ 0, dst.h, 0, dst.w }, BG);
	draw_keys(dst, s, t, now);
	draw_card(dst, t);
	draw_history(dst, s, t, now, right);

	const calc_lines l = calc_lines_of(s);
	const double since_clear = now - s->t_clear;
	const size_t a = strlen(s->cleared.expr), b = strlen(s->cleared.text);
	if (since_clear >= 0.0 && since_clear < CLEAR_STEP * (double)(a > b ? a : b) + CLEAR_CHAR) {
		draw_clearing(dst, s, t, since_clear, right);
		return;
	}
	draw_prompt(dst, s, &l, t, now);
	draw_result(dst, s, &l, t, now, right);
}
