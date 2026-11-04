/* Whole-buffer pixel operations: format conversion, dimming, cross-fading. */
#ifndef TREND_PIXELS_H
#define TREND_PIXELS_H

#include <stddef.h>
#include <stdint.h>

/* dst[n] RGBX = src[n] RGB, with X set to 0xff. */
void tr_rgb_to_rgbx(uint8_t *restrict dst, const uint8_t *restrict src, size_t n_pixels);

/* dst[i] = src[i] * q / 256 for n bytes. q is 0..256. */
void tr_scale_bytes(uint8_t *dst, const uint8_t *src, size_t n, int q);

/* dst += (src - dst) * a / 256 over a w_bytes x h rectangle. a is 0..256. */
void tr_blend_rect(uint8_t *dst, int dst_stride, const uint8_t *src, int src_stride,
                   int w_bytes, int h, int a);

/* One frame of the app open/close transition. With q and a in 0..256:
 *   rows < dy:  dst = back * q
 *   otherwise:  dst = back * q * (1 - a) + front[row - dy] * a
 * All three buffers are contiguous with row_bytes per row. */
void tr_slide_frame(uint8_t *restrict dst, const uint8_t *restrict back,
                    const uint8_t *restrict front, int row_bytes, int rows, int dy, int q, int a);

#endif
