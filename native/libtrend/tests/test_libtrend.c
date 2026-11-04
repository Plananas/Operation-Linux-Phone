/* Unit tests for libtrend. Run with: make test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "trend/draw.h"
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

int main(void)
{
	test_rgb_to_rgbx();
	test_slide_frame();
	test_fill_and_clip();
	test_surface_stride();
	test_round_rect();
	test_fill_mask();
	test_text();
	test_mesh();
	test_grid_blit();
	test_scope_idle();
	test_scope_audio();
	test_terrain();
	printf("%d checks, %d failures\n", checks, failures);
	return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
