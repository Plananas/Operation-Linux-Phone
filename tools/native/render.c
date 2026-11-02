/* librender: TREND OS 3D ASCII-object renderer (C core, called from trendos.py via ctypes).
 *
 * Same algorithm as the numpy path in trendos.py:
 *   - rotate face normals/centres, perspective-correct back-face cull (camera at (0,0,camz))
 *   - for each sampled point on a visible face: rotate, perspective-project to a character cell,
 *     depth-test against a z-buffer (nearest wins), shade by a point light
 *   - grid cell = palette_colour * ns + shade  (0 = empty)
 * and a blitter that copies the pre-rendered RGBX tile of every non-empty cell into a band.
 *
 * Build (on the phone): gcc -O2 -shared -fPIC -o librender.so render.c -lm
 */
#include <math.h>
#include <stdint.h>
#include <string.h>

#define MAXCELLS 4096   /* rows*cols upper bound (60*44 = 2640) */

int render_shape(const float *pts, const int32_t *fid, const int32_t *fstart, int nfaces,
                 const float *fnrm, const float *fcen, const int32_t *fcol,
                 const float *R, float K, int cols, int rows, float aspect, float camz,
                 const float *light, int ns, int32_t *grid)
{
	static float zbuf[MAXCELLS];
	int ncells = rows * cols, drawn = 0;
	(void)fid;                                 /* faces are contiguous ranges given by fstart */
	if (ncells > MAXCELLS) return -1;
	memset(grid, 0, sizeof(int32_t) * ncells);
	for (int i = 0; i < ncells; i++) zbuf[i] = 0.0f;          /* stores 1/z: larger = nearer */

	for (int f = 0; f < nfaces; f++) {
		const float *n0 = fnrm + 3 * f, *c0 = fcen + 3 * f;
		float nx = R[0] * n0[0] + R[1] * n0[1] + R[2] * n0[2];
		float ny = R[3] * n0[0] + R[4] * n0[1] + R[5] * n0[2];
		float nz = R[6] * n0[0] + R[7] * n0[1] + R[8] * n0[2];
		float cx = R[0] * c0[0] + R[1] * c0[1] + R[2] * c0[2];
		float cy = R[3] * c0[0] + R[4] * c0[1] + R[5] * c0[2];
		float cz = R[6] * c0[0] + R[7] * c0[1] + R[8] * c0[2] - camz;
		if (nx * cx + ny * cy + nz * cz >= 0.0f) continue;     /* faces away from the camera */
		int32_t base = fcol[f] * ns;
		for (int i = fstart[f]; i < fstart[f + 1]; i++) {
			const float *q = pts + 3 * i;
			float px = R[0] * q[0] + R[1] * q[1] + R[2] * q[2];
			float py = R[3] * q[0] + R[4] * q[1] + R[5] * q[2];
			float pz = R[6] * q[0] + R[7] * q[1] + R[8] * q[2];
			float ooz = 1.0f / (pz - camz), kz = K * ooz;
			int xp = (int)(cols * 0.5f + kz * px);
			int yp = (int)(rows * 0.5f - kz * py * aspect);
			if (xp < 0) xp = 0; else if (xp >= cols) xp = cols - 1;
			if (yp < 0) yp = 0; else if (yp >= rows) yp = rows - 1;
			int cell = yp * cols + xp;
			if (ooz <= zbuf[cell]) continue;
			zbuf[cell] = ooz;
			float lx = light[0] - px, ly = light[1] - py, lz = light[2] - pz;
			float lum = (nx * lx + ny * ly + nz * lz) / sqrtf(lx * lx + ly * ly + lz * lz);
			if (lum < 0.0f) lum = 0.0f; else if (lum > 1.0f) lum = 1.0f;
			int shade = (int)(powf(lum, 1.3f) * (ns - 1));
			if (shade > ns - 2) shade = ns - 2;
			grid[cell] = base + 1 + shade;
			drawn++;
		}
	}
	return drawn;
}

/* Copy the tile of every non-empty grid cell into dst (RGBX, row stride dst_stride bytes,
 * width dst_w px, height dst_h px) with the grid's top-left at pixel (x_off, y_off).
 * Clipped horizontally and vertically; empty cells are left untouched (clear dst first).
 * tiles: [ntiles][ch][cw][4]. */
void blit_grid(const int32_t *grid, int rows, int cols, const uint8_t *tiles, int ch, int cw,
               uint8_t *dst, int dst_stride, int dst_w, int dst_h, int x_off, int y_off)
{
	int tile_bytes = ch * cw * 4, row_bytes = cw * 4;
	for (int r = 0; r < rows; r++) {
		int y0 = y_off + r * ch;
		if (y0 + ch <= 0 || y0 >= dst_h) continue;
		for (int c = 0; c < cols; c++) {
			int32_t t = grid[r * cols + c];
			if (!t) continue;
			int x0 = x_off + c * cw;
			int a = x0 < 0 ? -x0 : 0, b = x0 + cw > dst_w ? dst_w - x0 : cw;   /* px range in tile */
			if (b <= a) continue;
			const uint8_t *src = tiles + (size_t)t * tile_bytes;
			for (int y = 0; y < ch; y++) {
				int yy = y0 + y;
				if (yy < 0 || yy >= dst_h) continue;
				memcpy(dst + (size_t)yy * dst_stride + (size_t)(x0 + a) * 4,
				       src + (size_t)y * row_bytes + a * 4, (size_t)(b - a) * 4);
			}
		}
	}
	(void)row_bytes;
}

/* render_shape + blit_grid in one call, drawing straight into dst (e.g. a framebuffer page).
 * Writes the pixel rectangle actually touched to rect_out[4] = {y0, y1, x0, x1} (clipped,
 * empty if y1 <= y0). Returns number of non-empty cells. */
int render_draw(const float *pts, const int32_t *fid, const int32_t *fstart, int nfaces,
                const float *fnrm, const float *fcen, const int32_t *fcol,
                const float *R, float K, int cols, int rows, float aspect, float camz,
                const float *light, int ns, const uint8_t *tiles, int ch, int cw,
                uint8_t *dst, int dst_stride, int dst_w, int dst_h, int x_off, int y_off,
                int32_t *rect_out)
{
	static int32_t grid[MAXCELLS];
	int r0 = rows, r1 = -1, c0 = cols, c1 = -1, cells = 0;
	if (render_shape(pts, fid, fstart, nfaces, fnrm, fcen, fcol, R, K, cols, rows, aspect,
	                 camz, light, ns, grid) < 0) return -1;
	for (int r = 0; r < rows; r++)
		for (int c = 0; c < cols; c++)
			if (grid[r * cols + c]) {
				cells++;
				if (r < r0) r0 = r;
				if (r > r1) r1 = r;
				if (c < c0) c0 = c;
				if (c > c1) c1 = c;
			}
	rect_out[0] = rect_out[1] = rect_out[2] = rect_out[3] = 0;
	if (!cells) return 0;
	blit_grid(grid, rows, cols, tiles, ch, cw, dst, dst_stride, dst_w, dst_h, x_off, y_off);
	int y0 = y_off + r0 * ch, y1 = y_off + (r1 + 1) * ch, x0 = x_off + c0 * cw, x1 = x_off + (c1 + 1) * cw;
	if (y0 < 0) y0 = 0;
	if (y1 > dst_h) y1 = dst_h;
	if (x0 < 0) x0 = 0;
	if (x1 > dst_w) x1 = dst_w;
	rect_out[0] = y0; rect_out[1] = y1; rect_out[2] = x0; rect_out[3] = x1;
	return cells;
}

/* dst[i] = src[i] * q / 256 for n bytes (dim a whole frame; q = 0..256). */
void scale_bytes(uint8_t *dst, const uint8_t *src, int n, int q)
{
	for (int i = 0; i < n; i++)
		dst[i] = (uint8_t)((src[i] * q) >> 8);
}

/* dst = dst + (src - dst) * a / 256 over a w_bytes x h rectangle (fade src in over dst). */
void blend_rect(uint8_t *dst, int dst_stride, const uint8_t *src, int src_stride, int w_bytes, int h, int a)
{
	for (int y = 0; y < h; y++) {
		uint8_t *d = dst + (size_t)y * dst_stride;
		const uint8_t *s = src + (size_t)y * src_stride;
		for (int x = 0; x < w_bytes; x++)
			d[x] = (uint8_t)(d[x] + (((int)s[x] - (int)d[x]) * a >> 8));
	}
}
