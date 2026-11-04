/* 2D drawing primitives for app screens. Every function draws into dst, clipped to its bounds,
 * and touches nothing else. */
#ifndef TREND_DRAW_H
#define TREND_DRAW_H

#include <stdint.h>

#include "trend/types.h"

/* A cached glyph: an 8-bit coverage mask positioned relative to the pen. mask == NULL means no
 * ink (a space). */
typedef struct {
	const uint8_t *mask;
	int w, h, dx, dy;
	float advance;
} tr_glyph;

void tr_fill_rect(tr_surface dst, tr_rect r, tr_colour c);

/* Fill rows r.y0, r.y0 + step, r.y0 + 2 * step, ... within r (CRT scanlines). */
void tr_fill_stripes(tr_surface dst, tr_rect r, int step, tr_colour c);

/* One-pixel-wide outline just inside r. */
void tr_stroke_rect(tr_surface dst, tr_rect r, tr_colour c);

/* Filled rectangle with corners of the given radius. */
void tr_fill_round_rect(tr_surface dst, tr_rect r, int radius, tr_colour c);

/* Colour c at the coverage of an 8-bit mask whose top-left is (x, y). */
void tr_fill_mask(tr_surface dst, const uint8_t *mask, int mask_w, int mask_h, int x, int y, tr_colour c);

/* Latin-1 text. font is a table of 256 glyphs, indexed by byte value. Returns the pen x after
 * the last character. */
float tr_draw_text(tr_surface dst, const tr_glyph *font, const uint8_t *text, int n, float x, int y, tr_colour c);

#endif
