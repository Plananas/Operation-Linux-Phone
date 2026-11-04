#include "trend/viz.h"

#include <math.h>
#include <string.h>

/* ---- oscilloscope ---- */

/* Start of the trace: the last rising zero crossing in the back half of the usable samples, so a
 * steady tone stands still on screen. Falls back to the end of the usable range. */
static int trigger_index(const int16_t *s, int n_usable)
{
	const int half = n_usable / 2;
	for (int i = n_usable - 2; i >= half; i--)
		if (s[i] < 0 && s[i + 1] >= 0)
			return i;
	return n_usable - 1;
}

static float abs_peak(const int16_t *s, int n)
{
	int peak = 0;
	for (int i = 0; i < n; i++)
		peak = tr_max(peak, s[i] < 0 ? -(int)s[i] : s[i]);
	return (float)peak;
}

static inline float maxf(float a, float b) { return a > b ? a : b; }

static inline void raise_pixel(uint8_t *p, int level)
{
	if (*p < level)
		*p = (uint8_t)level;
}

float tr_scope_frame(uint8_t *phos, int h, int w, tr_scope scope, float peak,
                     tr_surface dst, int x, int y)
{
	const int size = h * w;
	for (int i = 0; i < size; i++)
		phos[i] -= phos[i] >> 1;   /* phosphor decay: x 0.5 per frame */

	const float mid = (float)h / 2.0f;
	int rows[w];                       /* trace row per column */
	float next_peak = peak;
	int level = scope.idle_level;

	if (scope.samples) {
		const int16_t *seg = scope.samples + trigger_index(scope.samples, scope.n_samples - w);
		next_peak = maxf(maxf(abs_peak(seg, w), peak * 0.96f), 300.0f);
		const float gain = (mid - 6.0f) / next_peak;
		for (int c = 0; c < w; c++)
			rows[c] = tr_clamp((int)(mid - (float)seg[c] * gain), 2, h - 3);
		level = 255;
	} else {
		for (int c = 0; c < w; c++)
			rows[c] = tr_clamp((int)mid, 2, h - 3);
	}

	/* A halo just above and below each column's span, then the span itself on top. */
	for (int c = 0; c < w; c++) {
		const int next = rows[c + 1 < w ? c + 1 : c];
		raise_pixel(&phos[(tr_min(rows[c], next) - 1) * w + c], level / 2);
		raise_pixel(&phos[(tr_max(rows[c], next) + 1) * w + c], level / 2);
	}
	for (int c = 0; c < w; c++) {
		const int next = rows[c + 1 < w ? c + 1 : c];
		const int hi = tr_max(rows[c], next);
		for (int r = tr_min(rows[c], next); r <= hi; r++)
			phos[r * w + c] = (uint8_t)level;
	}

	for (int r = 0; r < h; r++) {
		uint32_t *out = tr_row32(dst, y + r) + x;
		const uint8_t *p = phos + r * w, *fl = scope.floor + r * w;
		uint8_t *q = phos + r * w;
		for (int c = 0; c < w; c++) {
			const uint8_t v = p[c] > fl[c] ? p[c] : fl[c];
			q[c] = v;
			out[c] = scope.lut[v];
		}
	}
	return next_peak;
}

/* ---- terrain ---- */

static inline int shade_of(float level, float dim, int shades)
{
	return 3 + tr_min((int)(level * (float)(shades - 4) * dim), shades - 4);
}

void tr_terrain_draw(tr_terrain t, const float *history, tr_atlas atlas, tr_surface dst, int x, int y)
{
	const int cells = t.rows * t.cols;
	int32_t grid[cells];
	int front[t.cols];                 /* highest row reached so far by nearer ridges, per column */
	memset(grid, 0, sizeof(grid));
	for (int c = 0; c < t.cols; c++)
		front[c] = t.rows;

	for (int ridge = 0; ridge < t.ridges; ridge++) {
		const float *levels = history + ridge * t.cols;
		const int at = ridge * t.cols;
		for (int c = 0; c < t.cols; c++) {
			if (!t.visible[at + c])
				continue;
			const int band = t.band[at + c];
			const float w = t.blend[at + c];
			const float level = levels[band] * (1.0f - w) + levels[band + 1] * w;
			const int row = tr_clamp((int)floorf(t.base[at + c] - level * t.amp[at + c]), 0, t.rows - 1);
			if (row >= front[c])
				continue;
			front[c] = row;
			grid[row * t.cols + c] = t.colour[ridge] + shade_of(level, t.dim[ridge], t.shades);
		}
	}

	const size_t tile_bytes = (size_t)atlas.ch * (size_t)atlas.cw * 4;
	const size_t line_bytes = (size_t)atlas.cw * 4;
	for (int r = 0; r < t.rows; r++)
		for (int c = 0; c < t.cols; c++) {
			const uint8_t *tile = atlas.px + (size_t)grid[r * t.cols + c] * tile_bytes;
			for (int line = 0; line < atlas.ch; line++)
				memcpy(dst.px + (size_t)(y + r * atlas.ch + line) * (size_t)dst.stride
				              + (size_t)(x + c * atlas.cw) * 4,
				       tile + (size_t)line * line_bytes, line_bytes);
		}
}
