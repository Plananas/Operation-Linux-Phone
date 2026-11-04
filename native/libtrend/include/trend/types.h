/* Plain value types shared by every libtrend module.
 *
 * House style (see native/README.md): functions read their inputs through const, write only to
 * the output they are explicitly handed, and keep no state between calls. Small structs are
 * passed by value. This keeps each function testable alone and safe to call from any thread.
 */
#ifndef TREND_TYPES_H
#define TREND_TYPES_H

#include <stddef.h>
#include <stdint.h>

/* A view of RGBX pixels owned by the caller. stride is in bytes and may exceed w * 4, so a
 * surface can describe a rectangle inside a larger page. */
typedef struct {
	uint8_t *px;
	int stride, w, h;
} tr_surface;

/* Half-open pixel rectangle: y0 <= y < y1, x0 <= x < x1. Empty when y1 <= y0 or x1 <= x0. */
typedef struct {
	int y0, y1, x0, x1;
} tr_rect;

/* A pixel in framebuffer byte order: R | G << 8 | B << 16 | X << 24 on this little-endian CPU. */
typedef uint32_t tr_colour;

static inline int tr_clamp(int v, int lo, int hi)
{
	return v < lo ? lo : v > hi ? hi : v;
}

static inline int tr_min(int a, int b) { return a < b ? a : b; }
static inline int tr_max(int a, int b) { return a > b ? a : b; }

static inline int tr_rect_is_empty(tr_rect r)
{
	return r.y1 <= r.y0 || r.x1 <= r.x0;
}

/* r limited to the bounds of s. */
static inline tr_rect tr_rect_clip(tr_rect r, tr_surface s)
{
	return (tr_rect){ tr_max(r.y0, 0), tr_min(r.y1, s.h), tr_max(r.x0, 0), tr_min(r.x1, s.w) };
}

static inline uint32_t *tr_row32(tr_surface s, int y)
{
	return (uint32_t *)(void *)(s.px + (size_t)y * (size_t)s.stride);
}

#endif
