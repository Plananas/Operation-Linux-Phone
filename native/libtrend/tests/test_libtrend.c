/* Unit tests for libtrend. Run with: make test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "trend/apps/calculator.h"
#include "trend/apps/files.h"
#include "trend/apps/music.h"
#include "trend/apps/web.h"
#include "trend/draw.h"
#include "trend/expr.h"
#include "trend/mesh.h"
#include "trend/pixels.h"
#include "trend/viz.h"

static int checks, failures;

#define CHECK(cond) do { \
	checks++; \
	if (!(cond)) { \
		failures++; \
		printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
	} \
} while (0)

#define RED 0xff0000ffu
#define BLUE 0xffff0000u

static uint32_t at(tr_surface s, int x, int y) { return tr_row32(s, y)[x]; }

static void test_rgb_to_rgbx(void)
{
	/* 37 pixels: crosses the 16-pixel NEON step and exercises the scalar tail. */
	enum { N = 37 };
	uint8_t src[N * 3], dst[N * 4];
	for (int i = 0; i < N * 3; i++)
		src[i] = (uint8_t)(i * 7);
	tr_rgb_to_rgbx(dst, src, N);
	for (int i = 0; i < N; i++) {
		CHECK(dst[i * 4] == src[i * 3]);
		CHECK(dst[i * 4 + 1] == src[i * 3 + 1]);
		CHECK(dst[i * 4 + 2] == src[i * 3 + 2]);
		CHECK(dst[i * 4 + 3] == 0xff);
	}
}

static void test_slide_frame(void)
{
	enum { W = 80, H = 20, ROW = W * 4, DY = 5 };
	static uint8_t back[ROW * H], front[ROW * H], dst[ROW * H];
	memset(back, 200, sizeof(back));
	memset(front, 100, sizeof(front));
	tr_slide_frame(dst, back, front, ROW, H, DY, 128, 128);
	CHECK(dst[0] == 100);                      /* above the front: back dimmed by half */
	CHECK(dst[ROW * DY - 1] == 100);
	CHECK(dst[ROW * DY] == 100);               /* (200 * 64 + 100 * 128) >> 8 */
	CHECK(dst[ROW * H - 1] == 100);
	/* a = 256, q = 0: exactly the front (saturated to 255 / 256 of it) */
	tr_slide_frame(dst, back, front, ROW, H, 0, 0, 256);
	CHECK(dst[0] == 99);
	CHECK(dst[ROW * H - 1] == 99);
}

static void test_fill_and_clip(void)
{
	uint32_t px[10 * 10] = { 0 };
	const tr_surface s = { (uint8_t *)px, 40, 10, 10 };
	tr_fill_rect(s, (tr_rect){ -5, 3, -5, 2 }, RED);   /* clipped at top-left */
	CHECK(at(s, 0, 0) == RED);
	CHECK(at(s, 1, 2) == RED);
	CHECK(at(s, 2, 2) == 0);
	CHECK(at(s, 0, 3) == 0);
	tr_fill_rect(s, (tr_rect){ 8, 50, 8, 50 }, BLUE);  /* clipped at bottom-right */
	CHECK(at(s, 9, 9) == BLUE);
	CHECK(at(s, 7, 9) == 0);
	tr_fill_rect(s, (tr_rect){ 20, 30, 20, 30 }, RED); /* entirely outside: no crash */
}

static void test_stripes(void)
{
	uint32_t px[10 * 4] = { 0 };
	const tr_surface s = { (uint8_t *)px, 16, 4, 10 };
	tr_fill_stripes(s, (tr_rect){ 1, 8, 1, 3 }, 3, RED);
	CHECK(at(s, 1, 1) == RED && at(s, 1, 4) == RED && at(s, 1, 7) == RED);
	CHECK(at(s, 1, 2) == 0 && at(s, 1, 8) == 0);
	CHECK(at(s, 0, 1) == 0 && at(s, 3, 1) == 0);
	memset(px, 0, sizeof(px));
	/* Clipped at the top: rows -2, 1, 4 ... stay in phase with the unclipped rectangle. */
	tr_fill_stripes(s, (tr_rect){ -2, 5, 0, 1 }, 3, BLUE);
	CHECK(at(s, 0, 0) == 0 && at(s, 0, 1) == BLUE && at(s, 0, 4) == BLUE);
	tr_fill_stripes(s, (tr_rect){ 0, 5, 0, 1 }, 0, RED);  /* a step of 0 must not hang */
	CHECK(at(s, 0, 0) == 0);
}

static void test_surface_stride(void)
{
	/* A surface inside a larger page must not touch pixels outside it. */
	uint32_t page[6 * 6] = { 0 };
	const tr_surface inner = { (uint8_t *)&page[6 + 1], 24, 2, 2 };
	tr_fill_rect(inner, (tr_rect){ 0, 99, 0, 99 }, RED);
	CHECK(page[6 + 1] == RED && page[6 + 2] == RED);
	CHECK(page[12 + 1] == RED && page[12 + 2] == RED);
	CHECK(page[6 + 3] == 0 && page[18 + 1] == 0 && page[6] == 0);
}

static void test_round_rect(void)
{
	uint32_t px[20 * 20] = { 0 };
	const tr_surface s = { (uint8_t *)px, 80, 20, 20 };
	tr_fill_round_rect(s, (tr_rect){ 0, 20, 0, 20 }, 6, RED);
	CHECK(at(s, 0, 0) == 0);                   /* corner cut */
	CHECK(at(s, 19, 19) == 0);
	CHECK(at(s, 10, 0) == RED);                /* edges kept */
	CHECK(at(s, 0, 10) == RED);
	CHECK(at(s, 10, 10) == RED);
	tr_fill_round_rect(s, (tr_rect){ -5, 25, -5, 25 }, 200, BLUE);  /* radius and bounds clamped */
	CHECK(at(s, 10, 10) == BLUE);
}

static void test_fill_mask(void)
{
	uint32_t px[4 * 4] = { 0 };
	const tr_surface s = { (uint8_t *)px, 16, 4, 4 };
	const uint8_t mask[] = { 255, 128, 0, 0 };
	tr_fill_mask(s, mask, 2, 2, 1, 1, RED);
	CHECK(at(s, 1, 1) == RED);                 /* full coverage: exact colour */
	CHECK((at(s, 2, 1) & 0xff) == 128);        /* half coverage: half way from black */
	CHECK(at(s, 1, 2) == 0);                   /* no coverage: untouched */
	tr_fill_mask(s, mask, 2, 2, -1, -1, BLUE); /* clipped: only mask[3], which is empty */
	CHECK(at(s, 0, 0) == 0);
	tr_fill_mask(s, mask, 2, 2, 3, 3, BLUE);   /* clipped at bottom-right */
	CHECK(at(s, 3, 3) == BLUE);
}

static void test_text(void)
{
	uint32_t px[8 * 20] = { 0 };
	const tr_surface s = { (uint8_t *)px, 80, 20, 8 };
	static tr_glyph font[256];
	const uint8_t ink[] = { 255, 255, 255, 255 };
	font['A'] = (tr_glyph){ ink, 2, 2, 1, 3, 5.5f };
	font[' '] = (tr_glyph){ NULL, 0, 0, 0, 0, 4.0f };
	const float end = tr_draw_text(s, font, (const uint8_t *)"A A", 3, 0.0f, 0, RED);
	CHECK(end == 15.0f);
	CHECK(at(s, 1, 3) == RED);                 /* first glyph at pen 0 + dx 1, y 0 + dy 3 */
	CHECK(at(s, 0, 3) == 0);
	CHECK(at(s, 10, 3) == RED);                /* second at pen 9.5 -> 9 + dx 1 */
	CHECK(at(s, 5, 3) == 0);                   /* the space drew nothing */
}

/* A single square facing the camera, one point per cell-ish. */
static void test_mesh(void)
{
	enum { COLS = 8, ROWS = 8, SHADES = 4, TILES = (1 + 1) * SHADES + 1 };
	const float pts[] = { 0, 0, -1,  0.2f, 0.2f, -1,  -0.2f, -0.2f, -1 };
	const int32_t fstart[] = { 0, 3 };
	const float nrm[] = { 0, 0, -1 }, cen[] = { 0, 0, -1 };
	const int32_t col[] = { 1 };
	const tr_mesh mesh = { pts, fstart, nrm, cen, col, 1 };
	const float identity[9] = { 1, 0, 0, 0, 1, 0, 0, 0, 1 };
	const tr_view view = { 4.0f, 1.0f, -5.0f, { 0, 0, -5 }, COLS, ROWS, SHADES };   /* camera looks along +z */
	int32_t grid[COLS * ROWS];

	const int drawn = tr_mesh_grid(mesh, identity, view, grid);
	CHECK(drawn >= 1 && drawn <= 3);
	int filled = 0;
	for (int i = 0; i < COLS * ROWS; i++)
		if (grid[i]) {
			filled++;
			CHECK(grid[i] > SHADES && grid[i] < TILES);      /* colour 1's tiles */
		}
	CHECK(filled == drawn);

	/* Turned 180 degrees about y, it faces away: culled. */
	const float away[9] = { -1, 0, 0, 0, 1, 0, 0, 0, -1 };
	CHECK(tr_mesh_grid(mesh, away, view, grid) == 0);
	for (int i = 0; i < COLS * ROWS; i++)
		CHECK(grid[i] == 0);

	/* Too many cells is refused, not overflowed. */
	const tr_view huge = { 4.0f, 1.0f, -5.0f, { 0, 0, -5 }, 100, 100, SHADES };
	CHECK(tr_mesh_grid(mesh, identity, huge, grid) == -1);
}

static void test_grid_blit(void)
{
	uint32_t px[6 * 6] = { 0 }, tiles[2 * 2 * 2];
	const tr_surface s = { (uint8_t *)px, 24, 6, 6 };
	const tr_atlas atlas = { (const uint8_t *)tiles, 2, 2 };
	for (int i = 0; i < 4; i++) {
		tiles[i] = 0;
		tiles[i + 4] = RED;
	}
	const int32_t grid[] = { 0, 1, 0, 0 };

	tr_rect r = tr_grid_blit(grid, 2, 2, atlas, s, 1, 1);
	CHECK(at(s, 3, 1) == RED && at(s, 4, 2) == RED);
	CHECK(at(s, 1, 1) == 0);                   /* empty cell untouched */
	CHECK(r.y0 == 1 && r.y1 == 3 && r.x0 == 3 && r.x1 == 5);

	r = tr_grid_blit(grid, 2, 2, atlas, s, 3, -1);  /* partly off the top-right */
	CHECK(r.y0 == 0 && r.y1 == 1 && r.x0 == 5 && r.x1 == 6);
	CHECK(at(s, 5, 0) == RED);

	const int32_t empty[4] = { 0, 0, 0, 0 };
	r = tr_grid_blit(empty, 2, 2, atlas, s, 0, 0);
	CHECK(tr_rect_is_empty(r));
}

static void identity_lut(uint32_t lut[256])
{
	for (uint32_t i = 0; i < 256; i++)
		lut[i] = i;
}

static void test_scope_idle(void)
{
	enum { H = 20, W = 30 };
	uint8_t phos[H * W], floor_[H * W];
	uint32_t px[H * W], lut[256];
	const tr_surface s = { (uint8_t *)px, W * 4, W, H };
	memset(phos, 0, sizeof(phos));
	memset(floor_, 7, sizeof(floor_));
	identity_lut(lut);
	const tr_scope scope = { NULL, 0, floor_, lut, 100 };

	const float peak = tr_scope_frame(phos, H, W, scope, 1234.0f, s, 0, 0);
	CHECK(peak == 1234.0f);                    /* no audio: the gain is left alone */
	CHECK(at(s, 5, H / 2) == 100);             /* the flat line */
	CHECK(at(s, 5, H / 2 - 1) == 50);          /* its halo */
	CHECK(at(s, 5, 0) == 7);                   /* the floor everywhere else */
}

static void test_scope_audio(void)
{
	enum { H = 40, W = 50, N = 400 };
	uint8_t phos[H * W], floor_[H * W];
	uint32_t px[H * W], lut[256];
	int16_t samples[N];
	const tr_surface s = { (uint8_t *)px, W * 4, W, H };
	memset(phos, 0, sizeof(phos));
	memset(floor_, 0, sizeof(floor_));
	identity_lut(lut);
	/* A full-scale square wave: exercises the extremes of every clamp and long vertical spans. */
	for (int i = 0; i < N; i++)
		samples[i] = i / 10 % 2 ? 32767 : -32768;
	const tr_scope scope = { samples, N, floor_, lut, 0 };

	const float peak = tr_scope_frame(phos, H, W, scope, 2000.0f, s, 0, 0);
	CHECK(peak == 32768.0f);                   /* -32768 must not overflow in abs */
	int lit = 0;
	for (int i = 0; i < H * W; i++)
		lit += phos[i] == 255;
	CHECK(lit > W);

	/* The next frame decays what was there. */
	const tr_scope silent = { NULL, 0, floor_, lut, 0 };
	tr_scope_frame(phos, H, W, silent, peak, s, 0, 0);
	for (int i = 0; i < H * W; i++)
		CHECK(phos[i] <= 128);

	/* Quiet audio: the auto-gain floor applies, and the peak decays towards it. */
	memset(samples, 0, sizeof(samples));
	const tr_scope quiet = { samples, N, floor_, lut, 0 };
	CHECK(tr_scope_frame(phos, H, W, quiet, 2000.0f, s, 0, 0) == 2000.0f * 0.96f);
	CHECK(tr_scope_frame(phos, H, W, quiet, 1.0f, s, 0, 0) == 300.0f);
}

static void test_terrain(void)
{
	enum { RIDGES = 2, COLS = 4, ROWS = 6, SHADES = 8, CH = 2, CW = 2 };
	int32_t band[RIDGES * COLS];
	float blend[RIDGES * COLS], base[RIDGES * COLS], amp[RIDGES * COLS];
	uint8_t visible[RIDGES * COLS];
	const int32_t colour[RIDGES] = { 0, SHADES };
	const float dim[RIDGES] = { 1.0f, 1.0f };
	float history[RIDGES * COLS];
	for (int i = 0; i < RIDGES * COLS; i++) {
		band[i] = tr_min(i % COLS, COLS - 2);
		blend[i] = i % COLS == COLS - 1 ? 1.0f : 0.0f;
		base[i] = 5.0f;
		amp[i] = 4.0f;
		visible[i] = 1;
		history[i] = 0.0f;
	}
	const tr_terrain t = { band, blend, base, amp, visible, colour, dim, RIDGES, COLS, ROWS, SHADES };

	enum { TILES = SHADES * 2, W = COLS * CW, H = ROWS * CH };
	static uint32_t atlas_px[TILES * CH * CW];
	for (int i = 0; i < TILES * CH * CW; i++)
		atlas_px[i] = (uint32_t)(i / (CH * CW));
	const tr_atlas atlas = { (const uint8_t *)atlas_px, CH, CW };
	uint32_t px[H * W];
	const tr_surface s = { (uint8_t *)px, W * 4, W, H };

	/* Flat history: the front ridge is drawn at the baseline, and hides the identical one behind. */
	tr_terrain_draw(t, history, atlas, s, 0, 0);
	CHECK(at(s, 0, 5 * CH) == 3);              /* colour 0, shade 3 */
	CHECK(at(s, 0, 0) == 0);                   /* empty background */

	/* A back ridge rising above the front one is visible over it, with its own colour. */
	history[COLS] = 1.0f;
	tr_terrain_draw(t, history, atlas, s, 0, 0);
	CHECK(at(s, 0, 5 * CH) == 3);              /* the front ridge, still */
	CHECK(at(s, 0, 1 * CH) == (uint32_t)(SHADES + 3 + SHADES - 4));

	/* A ridge at full height clamps to the top row instead of leaving the grid. */
	history[COLS] = 100.0f;
	tr_terrain_draw(t, history, atlas, s, 0, 0);
	CHECK(at(s, 0, 0) > SHADES);

	/* Columns outside a ridge's width don't draw. */
	memset(visible, 0, sizeof(visible));
	tr_terrain_draw(t, history, atlas, s, 0, 0);
	for (int i = 0; i < H * W; i++)
		CHECK(px[i] == 0);
}

static void test_dial(void)
{
	enum { ROWS = 2, COLS = 3, TAPE_W = 10, MIPS = 2 };
	static uint8_t mips[MIPS][ROWS][TAPE_W];
	for (int m = 0; m < MIPS; m++)
		for (int r = 0; r < ROWS; r++)
			for (int t = 0; t < TAPE_W; t++)
				mips[m][r][t] = (uint8_t)(m * 100 + r * 20 + t);
	const uint16_t key[ROWS * COLS] = { 0, 0, 0, 256, 256, 256 };
	static uint32_t lut[512];
	for (uint32_t i = 0; i < 512; i++)
		lut[i] = i;
	const double offset[COLS] = { 0.0, 1.0, 2.0 };
	const int32_t mip_of_col[COLS] = { 0, 1, 0 };
	const tr_dial d = { &mips[0][0][0], key, lut, offset, mip_of_col, 0.0, 1.0, ROWS, COLS, TAPE_W };
	uint32_t px[ROWS * COLS];
	const tr_surface s = { (uint8_t *)px, COLS * 4, COLS, ROWS };

	tr_dial_draw(d, 3.0, s, 0, 0);
	CHECK(at(s, 0, 0) == 3);                   /* mip 0, row 0, tape 3 */
	CHECK(at(s, 1, 0) == 100 + 4);             /* mip 1, tape 4 */
	CHECK(at(s, 2, 0) == 5);                   /* mip 0, tape 5 */
	CHECK(at(s, 0, 1) == 256 + 20 + 3);        /* row 1, with its key's high bits */

	tr_dial_draw(d, -50.0, s, 0, 0);           /* off the left end: clamped */
	CHECK(at(s, 0, 0) == 0);
	tr_dial_draw(d, 500.0, s, 0, 0);           /* off the right end: clamped */
	CHECK(at(s, 0, 0) == TAPE_W - 1);
}

static void check_result(const char *expr, const char *want)
{
	char out[64];
	const int ok = tr_expr_result(expr, out, sizeof(out));
	const int good = want ? ok && strcmp(out, want) == 0 : !ok;
	CHECK(good);
	if (!good)
		printf("  %s -> %s\n", expr, out);
}

static void test_expr(void)
{
	check_result("1+2*3", "7");
	check_result("(1+2)*3", "9");
	check_result("10/4", "2.5");
	check_result("-5+-(2)", "-7");
	check_result("--5", "5");
	check_result("0*-1", "0");                 /* never "-0" */
	check_result(".5+5.", "5.5");
	check_result("00", "0");
	check_result("007.5", "7.5");
	check_result("1e+20", "1e+20");
	check_result("999999999999999", "999999999999999");
	check_result("1000000000000000", "1e+15");
	check_result("1/3", "0.3333333333");
	check_result("1e308*10", "inf");
	/* errors */
	check_result("007", NULL);
	check_result("1/0", NULL);
	check_result("1/(2-2)", NULL);
	check_result("", NULL);
	check_result(".", NULL);
	check_result("1+", NULL);
	check_result("*5", NULL);
	check_result("()", NULL);
	check_result("(1", NULL);
	check_result("1)", NULL);
	check_result("2(3)", NULL);
	check_result("(2)3", NULL);
	check_result("1.2.3", NULL);
	check_result("1e", NULL);
	check_result("1e+", NULL);
	check_result("inf", NULL);
	check_result("Error", NULL);
}

static void press_all(tr_calc *s, const unsigned *keys, int n, double *now)
{
	for (int i = 0; i < n; i++) {
		tr_calc_press(s, s, keys[i], *now);
		*now += 1.0;
	}
}

static void test_calc_state(void)
{
	tr_calc *s = malloc(tr_calc_size());
	double now = 100.0;
	tr_calc_init(s);

	const unsigned sum[] = { '1', '2', '+', TR_CALC_MINUS, '3', '=' };  /* the - replaces the + */
	press_all(s, sum, 6, &now);
	CHECK(strcmp(tr_calc_expr(s), "9") == 0);

	const unsigned next[] = { '4' };                   /* a digit after a result starts fresh */
	press_all(s, next, 1, &now);
	CHECK(strcmp(tr_calc_expr(s), "4") == 0);

	const unsigned bad[] = { '/', '0', '=' };
	press_all(s, bad, 3, &now);
	CHECK(strcmp(tr_calc_expr(s), "Error") == 0);
	const unsigned after_error[] = { TR_CALC_DEL };    /* delete after a result clears it */
	press_all(s, after_error, 1, &now);
	CHECK(strcmp(tr_calc_expr(s), "") == 0);

	const unsigned chain[] = { '2', '=', TR_CALC_MUL, '3', '=' };      /* an operator continues */
	press_all(s, chain, 5, &now);
	CHECK(strcmp(tr_calc_expr(s), "6") == 0);

	for (int i = 0; i < 60; i++)                       /* the length limit holds */
		tr_calc_press(s, s, '7', now);
	CHECK(strlen(tr_calc_expr(s)) == 40);

	/* A tap presses a key; a drag off it doesn't. "7" is row 1, column 0. */
	tr_calc_press(s, s, 'C', now);
	tr_calc_touch(s, s, TR_TOUCH_DOWN, 20, 340, now);
	tr_calc_touch(s, s, TR_TOUCH_UP, 20, 340, now);
	CHECK(strcmp(tr_calc_expr(s), "7") == 0);
	tr_calc_touch(s, s, TR_TOUCH_DOWN, 20, 340, now);
	tr_calc_touch(s, s, TR_TOUCH_MOVE, 20, 100, now);
	tr_calc_touch(s, s, TR_TOUCH_UP, 20, 100, now);
	CHECK(strcmp(tr_calc_expr(s), "7") == 0);
	tr_calc_touch(s, s, TR_TOUCH_DOWN, 125, 340, now); /* the gap between keys */
	tr_calc_touch(s, s, TR_TOUCH_UP, 125, 340, now);
	CHECK(strcmp(tr_calc_expr(s), "7") == 0);
	tr_calc_touch(s, s, TR_TOUCH_DOWN, -5, -5, now);   /* off the keypad entirely */
	tr_calc_touch(s, s, TR_TOUCH_UP, 9999, 9999, now);
	CHECK(strcmp(tr_calc_expr(s), "7") == 0);

	/* Idle: the key is stable within a blink phase. A change moves it. */
	const double phase = (double)(int)((now + 10.0) / 0.53) * 0.53 + 0.1;
	const uint64_t k1 = tr_calc_frame_key(s, phase), k2 = tr_calc_frame_key(s, phase + 0.05);
	CHECK(k1 == k2);
	tr_calc_press(s, s, '1', phase);
	CHECK(tr_calc_frame_key(s, phase) != k1);
	free(s);
}

/* Every state and time renders within bounds; the sanitizers do most of the checking here. */
static void test_calc_render(void)
{
	static tr_glyph font[256];
	static const uint8_t ink[64] = { 255, 200, 100, 50 };
	for (int i = 0; i < 256; i++)
		font[i] = (tr_glyph){ ink, 8, 8, 0, -2, 9.5f };
	font[' '] = (tr_glyph){ NULL, 0, 0, 0, 0, 9.5f };
	const tr_calc_theme theme = { font, font, font, font, font, font, font, " .,-~:;=!*#$@", 13, RED, BLUE };
	enum { W = 480, H = 734 };
	static uint32_t px[H * W];
	const tr_surface dst = { (uint8_t *)px, W * 4, W, H };
	tr_calc *s = malloc(tr_calc_size());
	double now = 50.0;
	tr_calc_init(s);

	const unsigned keys[] = {
		'1', '/', '3', '=', '+', '7', '=', '(', '2', '=', '1', '/', '0', '=', 'C', '9', TR_CALC_MUL, '9', '=',
		'8', '8', '8', '8', '8', '8', '8', '8', '8', '8', '8', '8', '8', '8', '8', '8', TR_CALC_MUL, '9', '=',
		TR_CALC_DEL, 'C', '=',
	};
	for (size_t k = 0; k < sizeof(keys) / sizeof(keys[0]); k++) {
		tr_calc_press(s, s, keys[k], now);
		for (double dt = 0.0; dt < 1.0; dt += 0.043)
			tr_calc_render(s, &theme, now + dt, dst);
		now += 1.0;
	}
	for (int i = 0; i < 25; i++)                       /* a long expression and a long history */
		tr_calc_press(s, s, i % 2 ? '+' : '7', now);
	for (int i = 0; i < 5; i++) {
		tr_calc_press(s, s, '=', now);
		tr_calc_render(s, &theme, now + 0.05, dst);
		tr_calc_press(s, s, '+', now + 1.0);
		tr_calc_press(s, s, '1', now + 1.0);
		tr_calc_render(s, &theme, now + 1.05, dst);
		now += 2.0;
	}
	tr_calc_render(s, &theme, now, dst);
	const uint32_t idle_px = at(dst, 60, 345);
	tr_calc_touch(s, s, TR_TOUCH_DOWN, 20, 340, now);  /* a held key lights up */
	tr_calc_render(s, &theme, now, dst);
	CHECK(at(dst, 60, 345) != idle_px);
	CHECK(at(dst, 0, 0) == 0xff000000u);               /* outside everything: background */
	free(s);
}

static void test_music_text(void)
{
	char out[32];
	tr_music_display_name("/data/music/Some_Band/01_song.mp3", out, sizeof(out));
	CHECK(strcmp(out, "01 song") == 0);
	tr_music_display_name("no-extension", out, sizeof(out));
	CHECK(strcmp(out, "no-extension") == 0);
	tr_music_display_name(".hidden", out, sizeof(out));
	CHECK(strcmp(out, ".hidden") == 0);

	tr_music_latin1("caf\xc3\xa9", out, sizeof(out));                 /* in Latin-1 */
	CHECK(strcmp(out, "caf\xe9") == 0);
	tr_music_latin1("\xe2\x80\x99" "a\xe2\x80\x93" "b", out, sizeof(out));   /* punctuation */
	CHECK(strcmp(out, "'a-b") == 0);
	tr_music_latin1("\xe6\x97\xa5\xf0\x9f\x8e\xb5", out, sizeof(out));       /* outside it */
	CHECK(strcmp(out, "??") == 0);
	tr_music_latin1("old \xe9 tag", out, sizeof(out));                 /* not valid UTF-8 */
	CHECK(strcmp(out, "old \xe9 tag") == 0);
	tr_music_latin1("\xc3", out, sizeof(out));                         /* cut off at the end */
	CHECK(strcmp(out, "\xc3") == 0);
	tr_music_latin1("a\nb", out, sizeof(out));
	CHECK(strcmp(out, "a?b") == 0);

	char small[4];
	tr_music_latin1("abcdefgh", small, sizeof(small));
	CHECK(strcmp(small, "abc") == 0);
}

static tr_music_status music_status(int n_tracks)
{
	tr_music_status st;
	tr_music_status_init(&st, NULL);
	st.n_tracks = n_tracks;
	return st;
}

static tr_music_cmd music_tap(tr_music *s, const tr_music_status *st, int x, int y)
{
	tr_music_touch(s, s, st, TR_MUSIC_DOWN, x, y);
	return tr_music_touch(s, s, st, TR_MUSIC_UP, x, y);
}

static void test_music_touch(void)
{
	enum { KEY_Y = 336, ROW0 = 426, ROW_H = 44, BAR_Y = 249 };
	tr_music *s = malloc(tr_music_size());
	tr_music_init(s);
	tr_music_status st = music_status(20);
	tr_music_cmd c;

	CHECK(music_tap(s, &st, 90, KEY_Y).kind == TR_CMD_PREV);
	CHECK(music_tap(s, &st, 240, KEY_Y).kind == TR_CMD_TOGGLE);
	CHECK(music_tap(s, &st, 380, KEY_Y).kind == TR_CMD_NEXT);
	CHECK(music_tap(s, &st, 168, KEY_Y).kind == TR_CMD_NONE);     /* the gap between keys */
	CHECK(music_tap(s, &st, 5, 5).kind == TR_CMD_NONE);

	/* Sliding off a key cancels it. */
	tr_music_touch(s, s, &st, TR_MUSIC_DOWN, 240, KEY_Y);
	tr_music_touch(s, s, &st, TR_MUSIC_MOVE, 240, 100);
	CHECK(tr_music_touch(s, s, &st, TR_MUSIC_UP, 240, 100).kind == TR_CMD_NONE);

	/* A tap on a row plays it. */
	c = music_tap(s, &st, 200, ROW0 + 2 * ROW_H);
	CHECK(c.kind == TR_CMD_PLAY_TRACK && c.arg == 2);

	/* Past the end of a short list, nothing. */
	const tr_music_status few = music_status(2);
	CHECK(music_tap(s, &few, 200, ROW0 + 5 * ROW_H).kind == TR_CMD_NONE);

	/* A small wobble is still a tap. Dragging scrolls instead, and plays nothing. */
	tr_music_touch(s, s, &st, TR_MUSIC_DOWN, 200, ROW0 + 100);
	tr_music_touch(s, s, &st, TR_MUSIC_MOVE, 200, ROW0 + 104);
	CHECK(tr_music_touch(s, s, &st, TR_MUSIC_UP, 200, ROW0 + 104).kind == TR_CMD_PLAY_TRACK);
	tr_music_touch(s, s, &st, TR_MUSIC_DOWN, 200, ROW0 + 250);
	tr_music_touch(s, s, &st, TR_MUSIC_MOVE, 200, ROW0 + 250 - 2 * ROW_H);
	CHECK(tr_music_touch(s, s, &st, TR_MUSIC_UP, 200, ROW0 + 250 - 2 * ROW_H).kind == TR_CMD_NONE);
	c = music_tap(s, &st, 200, ROW0);                               /* the list has moved 2 rows */
	CHECK(c.kind == TR_CMD_PLAY_TRACK && c.arg == 2);

	/* It can't scroll past either end. */
	tr_music_touch(s, s, &st, TR_MUSIC_DOWN, 200, ROW0);
	tr_music_touch(s, s, &st, TR_MUSIC_MOVE, 200, ROW0 + 2000);
	tr_music_touch(s, s, &st, TR_MUSIC_UP, 200, ROW0 + 2000);
	c = music_tap(s, &st, 200, ROW0);
	CHECK(c.kind == TR_CMD_PLAY_TRACK && c.arg == 0);
	tr_music_touch(s, s, &st, TR_MUSIC_DOWN, 200, ROW0);
	tr_music_touch(s, s, &st, TR_MUSIC_MOVE, 200, ROW0 - 5000);
	tr_music_touch(s, s, &st, TR_MUSIC_UP, 200, ROW0 - 5000);
	c = music_tap(s, &st, 200, ROW0 + 6 * ROW_H);
	CHECK(c.kind == TR_CMD_PLAY_TRACK && c.arg == 19);

	/* Seeking: only with a known length, dragged anywhere, clamped to the bar. */
	CHECK(music_tap(s, &st, 240, BAR_Y).kind == TR_CMD_NONE);
	st.duration = 100.0;
	c = music_tap(s, &st, 240, BAR_Y);
	CHECK(c.kind == TR_CMD_SEEK && c.arg == 500);
	tr_music_touch(s, s, &st, TR_MUSIC_DOWN, 240, BAR_Y);
	tr_music_touch(s, s, &st, TR_MUSIC_MOVE, 9999, 700);
	c = tr_music_touch(s, s, &st, TR_MUSIC_UP, 9999, 700);
	CHECK(c.kind == TR_CMD_SEEK && c.arg == 1000);
	tr_music_touch(s, s, &st, TR_MUSIC_DOWN, 240, BAR_Y);
	tr_music_touch(s, s, &st, TR_MUSIC_MOVE, -50, BAR_Y);
	c = tr_music_touch(s, s, &st, TR_MUSIC_UP, -50, BAR_Y);
	CHECK(c.kind == TR_CMD_SEEK && c.arg == 0);

	/* Volume keys act when pressed. Other keys aren't ours. */
	c = tr_music_on_key(115, 1);
	CHECK(c.kind == TR_CMD_VOLUME && c.arg == 1);
	c = tr_music_on_key(114, 1);
	CHECK(c.kind == TR_CMD_VOLUME && c.arg == -1);
	c = tr_music_on_key(115, 0);
	CHECK(c.kind == TR_CMD_NONE && c.arg == 1);
	c = tr_music_on_key(30, 1);
	CHECK(c.kind == TR_CMD_NONE && c.arg == 0);
	free(s);
}

static void test_music_follow_and_key(void)
{
	tr_music *s = malloc(tr_music_size());
	tr_music_init(s);
	tr_music_status st = music_status(20);

	/* The track moving off screen brings it back. */
	st.track = 15;
	tr_music_follow(s, s, &st);
	tr_music_cmd c = music_tap(s, &st, 200, 412 + 6 * 44 + 2);
	CHECK(c.kind == TR_CMD_PLAY_TRACK && c.arg == 15);

	/* Stable while not playing, whatever the time. */
	const uint64_t k = tr_music_frame_key(s, &st, 1.0);
	CHECK(tr_music_frame_key(s, &st, 500.0) == k);
	st.volume = 3;
	CHECK(tr_music_frame_key(s, &st, 1.0) != k);

	/* Playing moves it, about 20 times a second. */
	st.state = TR_PLAYER_PLAYING;
	CHECK(tr_music_frame_key(s, &st, 1.0) != tr_music_frame_key(s, &st, 1.1));
	CHECK(tr_music_frame_key(s, &st, 1.001) == tr_music_frame_key(s, &st, 1.002));
	free(s);
}

/* The sanitizers do most of the checking here. */
static void test_music_render(void)
{
	static tr_glyph font[256];
	static const uint8_t ink[64] = { 255, 200, 100, 50 };
	for (int i = 0; i < 256; i++)
		font[i] = (tr_glyph){ ink, 8, 8, 0, -2, 9.5f };
	const tr_music_theme theme = { font, font, font, font, RED, BLUE, { NULL, 0, 0 }, 0 };
	enum { W = 480, H = 734 };
	static uint32_t px[H * W];
	static tr_music_library lib;
	const tr_surface dst = { (uint8_t *)px, W * 4, W, H };
	tr_music *s = malloc(tr_music_size());
	tr_music_init(s);

	/* Empty, then full of the longest names, with every track in turn playing. */
	tr_music_status st = music_status(0);
	tr_music_render(s, &st, &lib, NULL, &theme, dst);
	lib.n = TR_MUSIC_MAX_TRACKS;
	st.n_tracks = lib.n;
	for (int i = 0; i < lib.n; i++) {
		memset(lib.names[i], 'x', TR_MUSIC_NAME - 1);
		lib.names[i][TR_MUSIC_NAME - 1] = '\0';
	}
	memset(st.title, 'y', TR_MUSIC_NAME - 1);
	memset(st.error, 'z', TR_MUSIC_NAME - 1);
	st.state = TR_PLAYER_PLAYING;
	st.duration = 100000.0;
	for (int i = 0; i < TR_MUSIC_SCOPE; i++)
		st.scope[i] = i % 2 ? 32767 : -32768;           /* full scale stays inside the scope */
	for (st.track = 0; st.track < lib.n; st.track += 37) {
		st.position = st.track * 300.0;                 /* past the end, too */
		tr_music_follow(s, s, &st);
		tr_music_render(s, &st, &lib, NULL, &theme, dst);
	}

	/* The key being held and the playing track both show. */
	st.track = 0;
	tr_music_follow(s, s, &st);
	tr_music_render(s, &st, &lib, NULL, &theme, dst);
	const uint32_t idle_key = at(dst, 40, 306);
	tr_music_touch(s, s, &st, TR_MUSIC_DOWN, 40, 306);
	tr_music_render(s, &st, &lib, NULL, &theme, dst);
	CHECK(at(dst, 40, 306) != idle_key);
	tr_music_touch(s, s, &st, TR_MUSIC_UP, 40, 600);
	CHECK(at(dst, 20, 426) == RED);                         /* the marker on the current row */
	CHECK(at(dst, 0, 0) == 0xff000000u);
	free(s);
}

static void test_music_viz(void)
{
	enum { W = 480, H = 734, TAB_Y = 30, SONG_X = 100, VIZ_X = 350, PICTURE_Y0 = 58, PICTURE_Y1 = 520 };
	static tr_glyph font[256];
	static const uint8_t ink[64] = { 255, 200, 100, 50 };
	for (int i = 0; i < 256; i++)
		font[i] = (tr_glyph){ ink, 8, 8, 0, -2, 9.5f };
	/* An atlas whose every tile is one flat value, saying which colour it is. */
	enum { COLOURS = 10, SHADES = 13, CW = 8, CH = 12, TILES = COLOURS * SHADES };
	static uint32_t tiles[TILES][CH][CW];
	for (int t = 0; t < TILES; t++)
		for (int y = 0; y < CH; y++)
			for (int x = 0; x < CW; x++)
				tiles[t][y][x] = 0xff000000u | (uint32_t)(t / SHADES + 1);
	const tr_music_theme theme = { font, font, font, font, RED, BLUE, { (const uint8_t *)tiles, CH, CW }, SHADES };
	static uint32_t px[H * W], before[H * W];
	static tr_music_library lib;
	const tr_surface dst = { (uint8_t *)px, W * 4, W, H };
	tr_music *s = malloc(tr_music_size());
	tr_music_viz *v = malloc(tr_music_viz_size());
	tr_music_init(s);
	tr_music_viz_init(v);
	tr_music_status st = music_status(3);
	st.duration = 100.0;

	/* The tabs switch, and ask nothing of the player. Sliding off one cancels it. */
	CHECK(!tr_music_showing_viz(s));
	CHECK(music_tap(s, &st, VIZ_X, TAB_Y).kind == TR_CMD_NONE);
	CHECK(tr_music_showing_viz(s));
	CHECK(music_tap(s, &st, VIZ_X, TAB_Y).kind == TR_CMD_NONE);    /* already there */
	CHECK(tr_music_showing_viz(s));
	tr_music_touch(s, s, &st, TR_MUSIC_DOWN, SONG_X, TAB_Y);
	tr_music_touch(s, s, &st, TR_MUSIC_MOVE, SONG_X, 400);
	tr_music_touch(s, s, &st, TR_MUSIC_UP, SONG_X, 400);
	CHECK(tr_music_showing_viz(s));

	/* The controls still work on the visualiser tab, in their own places. The list isn't there. */
	CHECK(music_tap(s, &st, 240, 680).kind == TR_CMD_TOGGLE);
	CHECK(music_tap(s, &st, 90, 680).kind == TR_CMD_PREV);
	CHECK(music_tap(s, &st, 380, 680).kind == TR_CMD_NEXT);
	tr_music_cmd c = music_tap(s, &st, 240, 593);
	CHECK(c.kind == TR_CMD_SEEK && c.arg == 500);
	CHECK(music_tap(s, &st, 240, 300).kind == TR_CMD_NONE);        /* the picture */

	/* Back to the song tab: the same places do what they do there. */
	music_tap(s, &st, SONG_X, TAB_Y);
	CHECK(!tr_music_showing_viz(s));
	CHECK(music_tap(s, &st, 240, 336).kind == TR_CMD_TOGGLE);
	music_tap(s, &st, VIZ_X, TAB_Y);

	/* Loud music, at extremes that must stay in bounds, shows the whole palette. */
	st.state = TR_PLAYER_PLAYING;
	double now = 100.0;
	for (int f = 0; f < 200; f++) {
		for (int i = 0; i < TR_MUSIC_SCOPE; i++)
			st.scope[i] = i % 54 < 27 ? 32767 : -32768;
		now += 1.0 / 30.0;
		tr_music_viz_advance(v, &st, now);
		tr_music_render(s, &st, &lib, v, &theme, dst);
	}
	/* All the colours of the rainbow are in the picture, and white on top of the bars. */
	int seen[COLOURS + 1] = { 0 };
	for (int y = PICTURE_Y0; y < PICTURE_Y1; y++)
		for (int x = 0; x < W; x++) {
			const uint32_t p = at(dst, x, y);
			CHECK((p >> 24) == 0xff);
			if ((p & 0xffffff) <= COLOURS)
				seen[p & 0xffffff]++;
		}
	static const int RAINBOW_COLOURS[] = { 0, 6, 3, 1, 5, 2, 4 };
	for (int i = 0; i < 7; i++)
		CHECK(seen[RAINBOW_COLOURS[i] + 1] > 0);
	CHECK(seen[7 + 1] > 0);

	/* Paused: the picture holds still, and the screen isn't redrawn for it. */
	memcpy(before, px, sizeof(px));
	st.state = TR_PLAYER_PAUSED;
	const uint64_t key_paused = tr_music_frame_key(s, &st, now + 0.1);
	CHECK(tr_music_frame_key(s, &st, now + 0.1 + 0.0001) == key_paused);
	for (int f = 0; f < 10; f++) {
		now += 1.0 / 30.0;
		tr_music_viz_advance(v, &st, now);
	}
	tr_music_render(s, &st, &lib, v, &theme, dst);
	CHECK(memcmp(before + PICTURE_Y0 * W, px + PICTURE_Y0 * W, (size_t)(PICTURE_Y1 - PICTURE_Y0) * W * 4) == 0);

	/* Playing, it moves on, and the screen key asks for that. */
	st.state = TR_PLAYER_PLAYING;
	CHECK(tr_music_frame_key(s, &st, 1.0) != tr_music_frame_key(s, &st, 1.04));
	now += 1.0 / 30.0;
	tr_music_viz_advance(v, &st, now);
	tr_music_render(s, &st, &lib, v, &theme, dst);
	CHECK(memcmp(before + PICTURE_Y0 * W, px + PICTURE_Y0 * W, (size_t)(PICTURE_Y1 - PICTURE_Y0) * W * 4) != 0);

	/* After a long silence the levels are down, and a surface of any size is safe. */
	tr_music_status quiet = music_status(0);
	quiet.state = TR_PLAYER_STOPPED;
	for (int f = 0; f < 300; f++) {
		now += 1.0 / 30.0;
		tr_music_viz_advance(v, &quiet, now);
	}
	const tr_surface tiny = { (uint8_t *)px, W * 4, 40, 30 };
	tr_music_viz_draw(v, &theme, tiny);
	free(v);
	free(s);
}

static void feed(tr_files_status *st, const char *text)
{
	tr_files_feed(st, text, strlen(text));
}

static void test_files_status(void)
{
	tr_files_status *st = malloc(tr_files_status_size());
	tr_files *s = malloc(tr_files_size());
	tr_files_status_init(st);
	tr_files_init(s);
	CHECK(tr_files_phase(st) == TR_FILES_OFF);

	/* The key starts it, but only if the finger stays on it. */
	CHECK(tr_files_touch(s, s, st, TR_FILES_DOWN, 240, 670) == TR_FILES_NONE);
	CHECK(tr_files_touch(s, s, st, TR_FILES_MOVE, 240, 100) == TR_FILES_NONE);
	CHECK(tr_files_touch(s, s, st, TR_FILES_UP, 240, 670) == TR_FILES_NONE);
	tr_files_touch(s, s, st, TR_FILES_DOWN, 240, 670);
	CHECK(tr_files_touch(s, s, st, TR_FILES_UP, 240, 670) == TR_FILES_START);
	CHECK(tr_files_touch(s, s, st, TR_FILES_DOWN, 240, 100) == TR_FILES_NONE);
	CHECK(tr_files_touch(s, s, st, TR_FILES_UP, 240, 100) == TR_FILES_NONE);

	/* While starting it does nothing, then lines arrive cut at any point. */
	tr_files_set_phase(st, TR_FILES_STARTING, NULL);
	tr_files_touch(s, s, st, TR_FILES_DOWN, 240, 670);
	CHECK(tr_files_touch(s, s, st, TR_FILES_UP, 240, 670) == TR_FILES_NONE);
	feed(st, "U 1234");
	CHECK(tr_files_phase(st) == TR_FILES_STARTING);
	feed(st, "56 80\nA 192.168.0.2\nF 1048576\n");
	CHECK(tr_files_phase(st) == TR_FILES_ON);
	CHECK(strcmp(tr_files_pin(st), "123456") == 0);

	/* The key stops it, and the same text again doesn't redraw. */
	tr_files_touch(s, s, st, TR_FILES_DOWN, 240, 670);
	CHECK(tr_files_touch(s, s, st, TR_FILES_UP, 240, 670) == TR_FILES_STOP);
	const uint64_t key = tr_files_frame_key(s, st, 1.0);
	feed(st, "U 123456 80\nA 192.168.0.2\nF 1048576\n");
	CHECK(tr_files_frame_key(s, st, 50.0) == key);

	/* Something moving makes it animate; when it's finished, it stops. */
	feed(st, "T 0 u a 10 100 caf\xc3\xa9.mp3\n");
	CHECK(tr_files_frame_key(s, st, 1.0) != key);
	CHECK(tr_files_frame_key(s, st, 2.0) != tr_files_frame_key(s, st, 1.0));
	feed(st, "T 0 u k 100 100 caf\xc3\xa9.mp3\n");
	CHECK(tr_files_frame_key(s, st, 1.0) == tr_files_frame_key(s, st, 2.0));

	/* Nonsense from the server changes nothing and doesn't crash. */
	feed(st, "T 99 u a 1 1 x\nT -1 u a 1 1 x\nT\n\nQ what\nU\nU x\nF\n");
	char big[2000];
	memset(big, 'A', sizeof(big));
	big[0] = 'X';
	big[1] = ' ';
	tr_files_feed(st, big, sizeof(big));
	feed(st, "\n");
	CHECK(tr_files_phase(st) == TR_FILES_ON);

	/* Stopping keeps a reason given by the server, and a fresh start forgets it. */
	feed(st, "X too many wrong PINs\n");
	tr_files_set_phase(st, TR_FILES_OFF, NULL);
	CHECK(tr_files_phase(st) == TR_FILES_OFF);
	CHECK(strcmp(tr_files_pin(st), "") == 0);
	tr_files_set_phase(st, TR_FILES_STARTING, NULL);
	CHECK(tr_files_phase(st) == TR_FILES_STARTING);

	char text[32];
	tr_files_format_size(0, text, sizeof(text));
	CHECK(strcmp(text, "0 B") == 0);
	tr_files_format_size(1023, text, sizeof(text));
	CHECK(strcmp(text, "1023 B") == 0);
	tr_files_format_size(1536, text, sizeof(text));
	CHECK(strcmp(text, "1.5 KB") == 0);
	tr_files_format_size(INT64_C(3) << 30, text, sizeof(text));
	CHECK(strcmp(text, "3.0 GB") == 0);
	free(st);
	free(s);
}

/* Every state is drawn with a real font table and a long name, to catch overruns under the sanitizers. */
static void test_files_render(void)
{
	enum { W = 480, H = 734 };
	uint32_t *px = calloc(W * H, sizeof(*px));
	const tr_surface dst = { (uint8_t *)px, W * 4, W, H };
	static tr_glyph font[256];
	static const uint8_t ink[64] = { 255 };
	for (int i = 0; i < 256; i++)
		font[i] = (tr_glyph){ ink, 8, 8, 0, 0, 10.0f };
	const int32_t fstart[1] = { 0 };
	const float none[3] = { 0.0f, 0.0f, 0.0f };
	const int32_t col[1] = { 0 };
	const uint8_t tiles[12 * 8 * 4] = { 0 };
	const tr_files_theme theme = {
		font, font, font, font, font, RED, BLUE,
		{ none, fstart, none, none, col, 0 },
		{ 22.0f, 0.66f, -4.5f, { 0.0f, 0.0f, -1.0f }, TR_FILES_ICON_COLS, TR_FILES_ICON_ROWS, 1 },
		{ tiles, 12, 8 },
	};
	tr_files_status *st = malloc(tr_files_status_size());
	tr_files *s = malloc(tr_files_size());
	tr_files_status_init(st);
	tr_files_init(s);

	tr_files_render(s, st, &theme, 1.0, dst);
	CHECK(px[670 * W + 240] != 0);          /* the start key is lit */
	tr_files_set_phase(st, TR_FILES_STARTING, NULL);
	tr_files_render(s, st, &theme, 1.0, dst);
	feed(st, "U 000111 8080\nA 192.168.100.200\nF 12345678\n");
	tr_files_render(s, st, &theme, 1.0, dst);
	feed(st, "A \n");
	tr_files_render(s, st, &theme, 1.0, dst);
	char line[400];
	char name[300];
	memset(name, 'n', sizeof(name) - 1);
	name[sizeof(name) - 1] = '\0';
	for (int i = 0; i < 5; i++) {
		snprintf(line, sizeof(line), "T %d %c %c 5 10 %s\n", i, i % 2 ? 'd' : 'u', "akx"[i % 3], name);
		feed(st, line);
	}
	tr_files_render(s, st, &theme, 2.0, dst);
	tr_files_touch(s, s, st, TR_FILES_DOWN, 240, 670);
	tr_files_render(s, st, &theme, 2.0, dst);
	feed(st, "X the web port is in use and this reason goes on and on and on, past the card and beyond it\n");
	tr_files_set_phase(st, TR_FILES_OFF, NULL);
	tr_files_render(s, st, &theme, 3.0, dst);
	free(st);
	free(s);
	free(px);
}

/* ---- the Web app: everything it reads comes from a program that parses the internet ---- */

static size_t put_frame(uint8_t *out, int kind, const void *payload, size_t n)
{
	out[0] = (uint8_t)kind;
	out[1] = (uint8_t)n;
	out[2] = (uint8_t)(n >> 8);
	out[3] = (uint8_t)(n >> 16);
	memcpy(out + 4, payload, n);
	return n + 4;
}

static size_t put_row(uint8_t *out, int index, const void *bytes, size_t n)
{
	uint8_t p[300];
	p[0] = (uint8_t)index;
	p[1] = (uint8_t)(index >> 8);
	memcpy(p + 2, bytes, n);
	return put_frame(out, WEB_F_ROW, p, n + 2);
}

static tr_web_theme web_test_theme(tr_glyph *glyphs, const uint8_t *tiles)
{
	static const float pts[3] = { 0, 0, -1 }, nrm[3] = { 0, 0, -1 }, cen[3] = { 0, 0, -1 };
	static const int32_t start[2] = { 0, 1 }, col[1] = { 0 };
	const tr_mesh mesh = { pts, start, nrm, cen, col, 1 };
	const tr_view small = { 21.0f, 0.66f, -4.5f, { -2.5f, 3.0f, -5.0f }, 16, 8, 13 };
	const tr_view big = { 56.0f, 0.66f, -4.5f, { -2.5f, 3.0f, -5.0f }, 40, 22, 13 };
	return (tr_web_theme){ glyphs, glyphs, glyphs, 0xff00ff00u, 0xff0000ffu, mesh, small, big, { tiles, 12, 8 } };
}

static void test_web(void)
{
	static tr_glyph glyphs[256];
	static uint8_t mask[16 * 8];
	static uint8_t frame[1 << 20];
	memset(mask, 255, sizeof(mask));
	for (int i = 0; i < 256; i++)
		glyphs[i] = (tr_glyph){ mask, 8, 16, 0, 0, 10.0f };
	const size_t tile_bytes = (size_t)(WEB_PALETTE * WEB_SHADES + 1) * 12 * 8 * 4;
	uint8_t *tiles = calloc(1, tile_bytes);
	uint32_t *px = calloc(480 * 734, 4);
	const tr_surface dst = { (uint8_t *)px, 480 * 4, 480, 734 };
	tr_web_status *st = calloc(1, tr_web_status_size());
	tr_web *s = calloc(1, tr_web_size());
	const tr_web_theme theme = web_test_theme(glyphs, tiles);
	tr_web_init(s);
	tr_web_status_init(st);
	CHECK(tr_web_tab(s) == TR_WEB_CHAT);

	/* An empty screen draws, and a touch on nothing does nothing. */
	tr_web_advance(s, st, 1.0);
	tr_web_render(s, st, &theme, 1.0, dst);
	CHECK(tr_web_touch(s, s, st, TR_WEB_DOWN, 240, 400, 1.0).kind == TR_WEB_NONE);
	CHECK(tr_web_touch(s, s, st, TR_WEB_UP, 240, 400, 1.0).kind == TR_WEB_NONE);

	/* A link's cell gives its id, however the bytes were cut. */
	static const uint8_t row[] = { 'a', 'b', ' ', WEB_C_LINK, 0x01, 0x02, 'l', 'i', 'n', 'k', WEB_C_END, ' ', 'z' };
	size_t n = put_row(frame, 0, row, sizeof(row));
	for (size_t i = 0; i < n; i++)
		tr_web_feed(st, TR_WEB_PAGE, frame + i, 1);
	tr_web_set_tab(s, TR_WEB_PAGE);
	tr_web_advance(s, st, 2.0);
	tr_web_touch(s, s, st, TR_WEB_DOWN, WEB_MARGIN + 5 * WEB_ADVANCE, 85, 2.0);
	tr_web_cmd cmd = tr_web_touch(s, s, st, TR_WEB_UP, WEB_MARGIN + 5 * WEB_ADVANCE, 85, 2.0);
	CHECK(cmd.kind == TR_WEB_LINK && cmd.arg == 0x0102);

	/* The tabs and keys. */
	tr_web_touch(s, s, st, TR_WEB_DOWN, 40, 20, 3.0);
	CHECK(tr_web_touch(s, s, st, TR_WEB_UP, 40, 20, 3.0).kind == TR_WEB_NONE);
	CHECK(tr_web_tab(s) == TR_WEB_CHAT);
	tr_web_touch(s, s, st, TR_WEB_DOWN, 240, 700, 3.0);
	CHECK(tr_web_touch(s, s, st, TR_WEB_UP, 240, 700, 3.0).kind == TR_WEB_INPUT);
	tr_web_touch(s, s, st, TR_WEB_DOWN, 460, 20, 3.0);
	CHECK(tr_web_touch(s, s, st, TR_WEB_UP, 460, 20, 3.0).kind == TR_WEB_NEW_CHAT);
	tr_web_touch(s, s, st, TR_WEB_DOWN, 130, 20, 3.0);
	tr_web_touch(s, s, st, TR_WEB_UP, 130, 20, 3.0);
	CHECK(tr_web_tab(s) == TR_WEB_PAGE);
	tr_web_touch(s, s, st, TR_WEB_DOWN, 300, 20, 3.0);
	CHECK(tr_web_touch(s, s, st, TR_WEB_UP, 300, 20, 3.0).kind == TR_WEB_BACK);

	/* Scrolling stops at the ends, and a scroll order is obeyed but kept in range. */
	static const uint8_t art_or_text[] = { 'x' };
	n = 0;
	for (int i = 0; i < 500; i++)
		n += put_row(frame + n, i, art_or_text, 1);
	uint32_t where = 100000;
	n += put_frame(frame + n, WEB_F_SCROLL, &where, 4);
	tr_web_feed(st, TR_WEB_PAGE, frame, n);
	const uint64_t key = tr_web_advance(s, st, 4.0);
	CHECK(tr_web_scroll_of(s, TR_WEB_PAGE) == 500 * WEB_ROW_H - (668 - 78));
	CHECK(tr_web_advance(s, st, 4.0) == key);
	tr_web_render(s, st, &theme, 4.0, dst);

	/* Hostile input: bad lengths and truncated controls, in every position, on the last rows and past them. */
	static const uint8_t cut_link[] = { 'a', WEB_C_LINK };
	static const uint8_t cut_link2[] = { WEB_C_FIELD, 0x00 };
	static const uint8_t cut_field[] = { WEB_C_FIELD, 0, 1, 'x', 'y' };
	static const uint8_t art_short[] = { WEB_ART_MARK, 200, 255 };
	static uint8_t art_long[WEB_ROW_BYTES + 100];
	memset(art_long, 250, sizeof(art_long));
	art_long[0] = WEB_ART_MARK;
	n = put_row(frame, 490, cut_link, sizeof(cut_link));
	n += put_row(frame + n, 491, cut_link2, sizeof(cut_link2));
	n += put_row(frame + n, 492, cut_field, sizeof(cut_field));
	n += put_row(frame + n, 493, art_short, sizeof(art_short));
	n += put_row(frame + n, 494, art_long, sizeof(art_long));
	n += put_row(frame + n, 495, art_long + 1, sizeof(art_long) - 1);
	n += put_row(frame + n, 60000, row, sizeof(row));
	n += put_frame(frame + n, 99, row, sizeof(row));
	n += put_frame(frame + n, WEB_F_ROW, row, 1);
	n += put_frame(frame + n, WEB_F_ADDR, "", 0);
	n += put_frame(frame + n, WEB_F_STATUS, "\xff", 1);
	n += put_frame(frame + n, WEB_F_SCROLL, "ab", 2);
	n += put_frame(frame + n, WEB_F_ROWS, "\xff\xff", 2);
	tr_web_feed(st, TR_WEB_PAGE, frame, n);
	tr_web_advance(s, st, 5.0);
	tr_web_render(s, st, &theme, 5.0, dst);
	for (int y = 80; y < 660; y += 11)
		for (int x = 0; x < 480; x += 13) {
			tr_web_touch(s, s, st, TR_WEB_DOWN, x, y, 5.0);
			tr_web_touch(s, s, st, TR_WEB_UP, x, y, 5.0);
		}

	/* A frame too long to hold is dropped whole, and the next one still reads. */
	memset(frame, 'x', sizeof(frame));
	frame[0] = WEB_F_OPEN;
	frame[1] = 0;
	frame[2] = 0;
	frame[3] = 8;
	const size_t huge = 4 + (8u << 16);
	tr_web_feed(st, TR_WEB_CHAT, frame, sizeof(frame) < huge ? sizeof(frame) : huge);
	CHECK(tr_web_peek_open(st)[0] == '\0');
	n = put_frame(frame, WEB_F_OPEN, "https://x/\n\x01", 12);
	tr_web_feed(st, TR_WEB_PAGE, frame, n);
	CHECK(!strcmp(tr_web_peek_open(st), "https://x/"));
	tr_web_clear_open(st);
	CHECK(tr_web_peek_open(st)[0] == '\0');

	/* The address and status can't overrun however long they are. */
	static uint8_t long_text[3000];
	memset(long_text, 'a', sizeof(long_text));
	long_text[0] = 1;
	n = put_frame(frame, WEB_F_ADDR, long_text, 2000);
	n += put_frame(frame + n, WEB_F_STATUS, long_text, 2000);
	tr_web_feed(st, TR_WEB_PAGE, frame, n);
	CHECK(strlen(tr_web_address(st)) < 128);
	tr_web_advance(s, st, 6.0);
	tr_web_render(s, st, &theme, 6.0, dst);

	/* Typing draws too, at any length, including nothing. */
	static char typed[1500];
	memset(typed, 'k', sizeof(typed) - 1);
	tr_web_set_compose(s, typed, "label");
	tr_web_render(s, st, &theme, 6.0, dst);
	tr_web_set_compose(s, "", "label");
	tr_web_render(s, st, &theme, 6.0, dst);
	tr_web_set_compose(s, NULL, NULL);

	/* Going back to the chat, it follows the bottom until pulled up. */
	n = 0;
	for (int i = 0; i < 300; i++)
		n += put_row(frame + n, i, art_or_text, 1);
	tr_web_feed(st, TR_WEB_CHAT, frame, n);
	tr_web_set_tab(s, TR_WEB_CHAT);
	tr_web_advance(s, st, 7.0);
	const int bottom = 300 * WEB_ROW_H - (668 - 144);
	CHECK(tr_web_scroll_of(s, TR_WEB_CHAT) == bottom);
	tr_web_touch(s, s, st, TR_WEB_DOWN, 240, 300, 7.0);
	tr_web_touch(s, s, st, TR_WEB_MOVE, 240, 400, 7.2);
	tr_web_touch(s, s, st, TR_WEB_UP, 240, 400, 7.6);
	tr_web_advance(s, st, 8.0);
	CHECK(tr_web_scroll_of(s, TR_WEB_CHAT) == bottom - 100);
	n = put_row(frame, 300, art_or_text, 1);
	tr_web_feed(st, TR_WEB_CHAT, frame, n);
	tr_web_advance(s, st, 9.0);
	CHECK(tr_web_scroll_of(s, TR_WEB_CHAT) == bottom - 100);
	free(s);
	free(st);
	free(px);
	free(tiles);
}

int main(void)
{
	test_rgb_to_rgbx();
	test_slide_frame();
	test_fill_and_clip();
	test_stripes();
	test_surface_stride();
	test_round_rect();
	test_fill_mask();
	test_text();
	test_mesh();
	test_grid_blit();
	test_scope_idle();
	test_scope_audio();
	test_terrain();
	test_dial();
	test_expr();
	test_calc_state();
	test_calc_render();
	test_music_text();
	test_music_touch();
	test_music_follow_and_key();
	test_music_render();
	test_music_viz();
	test_files_status();
	test_files_render();
	test_web();
	printf("%d checks, %d failures\n", checks, failures);
	return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
