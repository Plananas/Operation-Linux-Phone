#include "ascii.h"

#include <stdlib.h>
#include <string.h>

#include "trend/apps/web_wire.h"

enum { RED, GREEN, BLUE, YELLOW, MAGENTA, CYAN, ORANGE, WHITE };       /* tos/config.py PALETTE */

static unsigned hue_of(unsigned r, unsigned g, unsigned b, unsigned max, unsigned min)
{
	const float span = (float)(max - min);
	float h;
	if (max == r)
		h = ((float)g - (float)b) / span;
	else if (max == g)
		h = 2.0f + ((float)b - (float)r) / span;
	else
		h = 4.0f + ((float)r - (float)g) / span;
	h *= 60.0f;
	if (h < 0.0f)
		h += 360.0f;
	if (h < 18.0f || h >= 335.0f) return RED;
	if (h < 42.0f) return ORANGE;
	if (h < 80.0f) return YELLOW;
	if (h < 160.0f) return GREEN;
	if (h < 200.0f) return CYAN;
	if (h < 275.0f) return BLUE;
	return MAGENTA;
}

/* The tile for a colour at a brightness from 0 to 1. */
static uint8_t tile_at(unsigned r, unsigned g, unsigned b, float level)
{
	const unsigned max = r > g ? (r > b ? r : b) : (g > b ? g : b);
	const unsigned min = r < g ? (r < b ? r : b) : (g < b ? g : b);
	const int shade = (int)(level * (float)(WEB_SHADES - 1) + 0.5f);
	if (shade <= 0)
		return 0;
	const int grey = max - min < 24u || (max - min) * 5u < max;
	const unsigned colour = grey ? WHITE : hue_of(r, g, b, max, min);
	return (uint8_t)(colour * WEB_SHADES + (unsigned)shade);
}

uint8_t ascii_tile(unsigned r, unsigned g, unsigned b)
{
	const unsigned max = r > g ? (r > b ? r : b) : (g > b ? g : b);
	return tile_at(r, g, b, (float)max / 255.0f);
}

static unsigned luma_of(const uint8_t *c)
{
	return (77u * c[0] + 150u * c[1] + 29u * c[2]) >> 8;
}

/* The darkest and brightest levels worth keeping: the ends of the histogram, without the odd stray cell. */
static void level_range(const uint8_t *cells, int n, unsigned *lo, unsigned *hi)
{
	unsigned hist[256] = { 0 };
	for (int i = 0; i < n; i++)
		hist[luma_of(cells + i * 3)]++;
	const unsigned skip = (unsigned)n / 50u;
	unsigned seen = 0, v = 0;
	while (v < 255 && seen + hist[v] <= skip)
		seen += hist[v++];
	*lo = v;
	seen = 0;
	v = 255;
	while (v > 0 && seen + hist[v] <= skip)
		seen += hist[v--];
	*hi = v;
}

void ascii_image(const uint8_t *rgb, int w, int h, int cols, int rows, uint8_t *out)
{
	memset(out, 0, (size_t)cols * (size_t)rows);
	if (w <= 0 || h <= 0)
		return;
	/* Cell width over height is 2/3, so a square picture needs 2 rows for every 3 columns. */
	int fit_cols = cols;
	int fit_rows = (int)((double)cols * h / w * 2.0 / 3.0 + 0.5);
	if (fit_rows > rows) {
		fit_rows = rows;
		fit_cols = (int)((double)rows * w / h * 3.0 / 2.0 + 0.5);
	}
	fit_cols = fit_cols < 1 ? 1 : fit_cols > cols ? cols : fit_cols;
	fit_rows = fit_rows < 1 ? 1 : fit_rows;
	const int x0 = (cols - fit_cols) / 2, y0 = (rows - fit_rows) / 2;
	uint8_t *cells = malloc((size_t)fit_cols * (size_t)fit_rows * 3);
	if (!cells)
		return;
	for (int cy = 0; cy < fit_rows; cy++) {
		const int py0 = (int)((long long)cy * h / fit_rows);
		int py1 = (int)((long long)(cy + 1) * h / fit_rows);
		py1 = py1 <= py0 ? py0 + 1 : py1;
		for (int cx = 0; cx < fit_cols; cx++) {
			const int px0 = (int)((long long)cx * w / fit_cols);
			int px1 = (int)((long long)(cx + 1) * w / fit_cols);
			px1 = px1 <= px0 ? px0 + 1 : px1;
			unsigned long sum[3] = { 0, 0, 0 }, count = 0;
			for (int y = py0; y < py1 && y < h; y++)
				for (int x = px0; x < px1 && x < w; x++) {
					const uint8_t *p = rgb + ((size_t)y * (size_t)w + (size_t)x) * 3;
					sum[0] += p[0];
					sum[1] += p[1];
					sum[2] += p[2];
					count++;
				}
			uint8_t *c = cells + ((size_t)cy * (size_t)fit_cols + (size_t)cx) * 3;
			for (int k = 0; k < 3; k++)
				c[k] = (uint8_t)(count ? sum[k] / count : 0);
		}
	}
	unsigned lo, hi;
	level_range(cells, fit_cols * fit_rows, &lo, &hi);
	/* A flat picture has no range to stretch. */
	const float span = hi > lo + 16 ? (float)(hi - lo) : 0.0f;
	for (int cy = 0; cy < fit_rows; cy++)
		for (int cx = 0; cx < fit_cols; cx++) {
			const uint8_t *c = cells + ((size_t)cy * (size_t)fit_cols + (size_t)cx) * 3;
			const unsigned luma = luma_of(c);
			float level = span > 0.0f ? ((float)luma - (float)lo) / span : (float)luma / 255.0f;
			level = level < 0.0f ? 0.0f : level > 1.0f ? 1.0f : level;
			out[(y0 + cy) * cols + x0 + cx] = tile_at(c[0], c[1], c[2], level);
		}
	free(cells);
}
