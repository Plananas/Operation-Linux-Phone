#include "trend/pixels.h"

#ifdef __ARM_NEON
#include <arm_neon.h>
#endif

void tr_rgb_to_rgbx(uint8_t *restrict dst, const uint8_t *restrict src, size_t n_pixels)
{
	size_t i = 0;
#ifdef __ARM_NEON
	/* vld3 de-interleaves, vst4 re-interleaves: 16 pixels per step. */
	const uint8x16_t x = vdupq_n_u8(0xff);
	for (; i + 16 <= n_pixels; i += 16) {
		__builtin_prefetch(src + i * 3 + 320);
		const uint8x16x3_t c = vld3q_u8(src + i * 3);
		const uint8x16x4_t out = { { c.val[0], c.val[1], c.val[2], x } };
		vst4q_u8(dst + i * 4, out);
	}
#endif
	for (; i < n_pixels; i++) {
		dst[i * 4] = src[i * 3];
		dst[i * 4 + 1] = src[i * 3 + 1];
		dst[i * 4 + 2] = src[i * 3 + 2];
		dst[i * 4 + 3] = 0xff;
	}
}

void tr_scale_bytes(uint8_t *dst, const uint8_t *src, size_t n, int q)
{
	for (size_t i = 0; i < n; i++)
		dst[i] = (uint8_t)((src[i] * q) >> 8);
}

void tr_blend_rect(uint8_t *dst, int dst_stride, const uint8_t *src, int src_stride,
                   int w_bytes, int h, int a)
{
	for (int y = 0; y < h; y++) {
		uint8_t *d = dst + (size_t)y * (size_t)dst_stride;
		const uint8_t *s = src + (size_t)y * (size_t)src_stride;
		for (int x = 0; x < w_bytes; x++)
			d[x] = (uint8_t)(d[x] + (((int)s[x] - (int)d[x]) * a >> 8));
	}
}

/* Computed as (back * (q * (256 - a) >> 8) + front * a) >> 8, at most 1 level off the exact
 * formula. NEON, 64 bytes per step: the Cortex-A7 is in-order, so four independent 16-byte lanes
 * are loaded before any is used (hides the load latency), with software prefetch for both input
 * streams. Measured per 480x800 frame (2026-11-03): plain C 10.5 ms, NEON 16 bytes per step
 * 7.9 ms, this 4.5 ms. */
#ifdef __ARM_NEON
#define SLIDE_PREFETCH 320
#define SLIDE_MIX(b, c) vcombine_u8( \
	vshrn_n_u16(vmlal_u8(vmull_u8(vget_low_u8(b), vqa), vget_low_u8(c), va), 8), \
	vshrn_n_u16(vmlal_u8(vmull_u8(vget_high_u8(b), vqa), vget_high_u8(c), va), 8))
#endif

void tr_slide_frame(uint8_t *restrict dst, const uint8_t *restrict back,
                    const uint8_t *restrict front, int row_bytes, int rows, int dy, int q, int a)
{
	const int n0 = dy * row_bytes, n = rows * row_bytes;
	const int qa = (q * (256 - a)) >> 8 > 255 ? 255 : (q * (256 - a)) >> 8;
	const int dim = q > 255 ? 255 : q;
	const int fade = a > 255 ? 255 : a;
	const uint8_t *f = front - n0;     /* front row r - dy, as a flat offset */
	int i = 0;
	for (; i < n0; i++)                /* the strip above the sliding front: dim only (small) */
		dst[i] = (uint8_t)((back[i] * dim) >> 8);
#ifdef __ARM_NEON
	const uint8x8_t vqa = vdup_n_u8((uint8_t)qa), va = vdup_n_u8((uint8_t)fade);
	for (; i + 64 <= n; i += 64) {
		__builtin_prefetch(back + i + SLIDE_PREFETCH);
		__builtin_prefetch(f + i + SLIDE_PREFETCH);
		const uint8x16_t b0 = vld1q_u8(back + i), b1 = vld1q_u8(back + i + 16);
		const uint8x16_t b2 = vld1q_u8(back + i + 32), b3 = vld1q_u8(back + i + 48);
		const uint8x16_t c0 = vld1q_u8(f + i), c1 = vld1q_u8(f + i + 16);
		const uint8x16_t c2 = vld1q_u8(f + i + 32), c3 = vld1q_u8(f + i + 48);
		const uint8x16_t r0 = SLIDE_MIX(b0, c0), r1 = SLIDE_MIX(b1, c1);
		const uint8x16_t r2 = SLIDE_MIX(b2, c2), r3 = SLIDE_MIX(b3, c3);
		vst1q_u8(dst + i, r0);
		vst1q_u8(dst + i + 16, r1);
		vst1q_u8(dst + i + 32, r2);
		vst1q_u8(dst + i + 48, r3);
	}
#endif
	for (; i < n; i++)
		dst[i] = (uint8_t)((back[i] * qa + f[i] * fade) >> 8);
}
