#include "trend/draw.h"

#include <math.h>

static inline void fill_span(uint32_t *row, int x0, int x1, tr_colour c)
{
	for (int x = x0; x < x1; x++)
		row[x] = c;
}

void tr_fill_rect(tr_surface dst, tr_rect r, tr_colour c)
{
	const tr_rect clip = tr_rect_clip(r, dst);
	if (tr_rect_is_empty(clip))
		return;
	for (int y = clip.y0; y < clip.y1; y++)
		fill_span(tr_row32(dst, y), clip.x0, clip.x1, c);
}

void tr_fill_stripes(tr_surface dst, tr_rect r, int step, tr_colour c)
{
	const tr_rect clip = tr_rect_clip(r, dst);
	if (tr_rect_is_empty(clip) || step < 1)
		return;
	const int skipped = clip.y0 - r.y0;            /* stay in phase when clipped at the top */
	const int first = clip.y0 + (step - skipped % step) % step;
	for (int y = first; y < clip.y1; y += step)
		fill_span(tr_row32(dst, y), clip.x0, clip.x1, c);
}

void tr_stroke_rect(tr_surface dst, tr_rect r, tr_colour c)
{
	tr_fill_rect(dst, (tr_rect){ r.y0, r.y0 + 1, r.x0, r.x1 }, c);
	tr_fill_rect(dst, (tr_rect){ r.y1 - 1, r.y1, r.x0, r.x1 }, c);
	tr_fill_rect(dst, (tr_rect){ r.y0, r.y1, r.x0, r.x0 + 1 }, c);
	tr_fill_rect(dst, (tr_rect){ r.y0, r.y1, r.x1 - 1, r.x1 }, c);
}

/* How far a row sits in from the rectangle's edge because of the corner circle. */
static inline int corner_inset(int row_from_edge, int radius)
{
	if (row_from_edge >= radius)
		return 0;
	const float d = (float)radius - (float)row_from_edge - 0.5f;
	return (int)((float)radius - sqrtf((float)(radius * radius) - d * d) + 0.5f);
}

void tr_fill_round_rect(tr_surface dst, tr_rect r, int radius, tr_colour c)
{
	const int h = r.y1 - r.y0, w = r.x1 - r.x0;
	const int rad = tr_clamp(radius, 0, tr_min(h, w) / 2);
	const int top = tr_max(r.y0, 0), bottom = tr_min(r.y1, dst.h);
	for (int y = top; y < bottom; y++) {
		const int inset = corner_inset(tr_min(y - r.y0, r.y1 - 1 - y), rad);
		const int x0 = tr_max(r.x0 + inset, 0), x1 = tr_min(r.x1 - inset, dst.w);
		fill_span(tr_row32(dst, y), x0, x1, c);
	}
}

/* d + (c - d) * m / 255 on all channels but X, using the 8-bit SWAR form of d * (256 - a) + c * a. */
static inline uint32_t mix_pixel(uint32_t d, tr_colour c, unsigned m)
{
	const unsigned a = m + (m >> 7);   /* maps 0..255 to 0..256 */
	const uint32_t rb = ((d & 0x00ff00ffu) * (256 - a) + (c & 0x00ff00ffu) * a) >> 8;
	const uint32_t g = ((d & 0x0000ff00u) * (256 - a) + (c & 0x0000ff00u) * a) >> 8;
	return (rb & 0x00ff00ffu) | (g & 0x0000ff00u) | (c & 0xff000000u);
}

void tr_fill_mask(tr_surface dst, const uint8_t *mask, int mask_w, int mask_h, int x, int y, tr_colour c)
{
	const int first = y < 0 ? -y : 0, last = tr_min(mask_h, dst.h - y);
	const int from = x < 0 ? -x : 0, to = tr_min(mask_w, dst.w - x);
	if (to <= from)
		return;
	for (int line = first; line < last; line++) {
		const uint8_t *m = mask + (size_t)line * (size_t)mask_w;
		uint32_t *row = tr_row32(dst, y + line) + x;
		for (int i = from; i < to; i++) {
			if (m[i] == 255)
				row[i] = c;
			else if (m[i])
				row[i] = mix_pixel(row[i], c, m[i]);
		}
	}
}

float tr_draw_text(tr_surface dst, const tr_glyph *font, const uint8_t *text, int n, float x, int y, tr_colour c)
{
	float pen = x;
	for (int i = 0; i < n; i++) {
		const tr_glyph g = font[text[i]];
		if (g.mask)
			tr_fill_mask(dst, g.mask, g.w, g.h, (int)pen + g.dx, y + g.dy, c);
		pen += g.advance;
	}
	return pen;
}
