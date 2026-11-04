#include "trend/mesh.h"

#include <math.h>
#include <string.h>

typedef struct { float x, y, z; } vec3;

static inline vec3 rotate(const float r[9], const float *v)
{
	return (vec3){
		r[0] * v[0] + r[1] * v[1] + r[2] * v[2],
		r[3] * v[0] + r[4] * v[1] + r[5] * v[2],
		r[6] * v[0] + r[7] * v[1] + r[8] * v[2],
	};
}

static inline float dot(vec3 a, vec3 b)
{
	return a.x * b.x + a.y * b.y + a.z * b.z;
}

/* Character density for a point on a face, from a point light. Index 0 .. shades - 2. */
static inline int shade_of(vec3 normal, vec3 p, const float light[3], int shades)
{
	const vec3 to_light = { light[0] - p.x, light[1] - p.y, light[2] - p.z };
	const float lum = dot(normal, to_light) / sqrtf(dot(to_light, to_light));
	const float clamped = lum < 0.0f ? 0.0f : lum > 1.0f ? 1.0f : lum;
	return tr_min((int)(powf(clamped, 1.3f) * (float)(shades - 1)), shades - 2);
}

int tr_mesh_grid(tr_mesh mesh, const float r[9], tr_view view, int32_t *grid)
{
	const int cells = view.rows * view.cols;
	if (cells > TR_MESH_MAX_CELLS)
		return -1;

	float nearest[TR_MESH_MAX_CELLS];  /* 1/z of the point in each cell: larger = nearer */
	int drawn = 0;
	memset(nearest, 0, sizeof(float) * (size_t)cells);
	memset(grid, 0, sizeof(int32_t) * (size_t)cells);

	for (int f = 0; f < mesh.nfaces; f++) {
		const vec3 normal = rotate(r, mesh.fnrm + 3 * f);
		vec3 centre = rotate(r, mesh.fcen + 3 * f);
		centre.z -= view.cam_z;
		if (dot(normal, centre) >= 0.0f)
			continue;              /* faces away from the camera */

		const int32_t base = mesh.fcol[f] * view.shades;
		for (int i = mesh.fstart[f]; i < mesh.fstart[f + 1]; i++) {
			const vec3 p = rotate(r, mesh.pts + 3 * i);
			const float ooz = 1.0f / (p.z - view.cam_z), kz = view.k * ooz;
			const int col = tr_clamp((int)((float)view.cols * 0.5f + kz * p.x), 0, view.cols - 1);
			const int row = tr_clamp((int)((float)view.rows * 0.5f - kz * p.y * view.aspect), 0, view.rows - 1);
			const int cell = row * view.cols + col;
			if (ooz <= nearest[cell])
				continue;
			nearest[cell] = ooz;
			grid[cell] = base + 1 + shade_of(normal, p, view.light, view.shades);
			drawn++;
		}
	}
	return drawn;
}

/* Copy one tile, clipped to dst. */
static inline void blit_tile(const uint8_t *tile, tr_atlas atlas, tr_surface dst, int x, int y)
{
	const int from = x < 0 ? -x : 0, to = tr_min(atlas.cw, dst.w - x);
	if (to <= from)
		return;
	const int first = y < 0 ? -y : 0, last = tr_min(atlas.ch, dst.h - y);
	for (int line = first; line < last; line++)
		memcpy(dst.px + (size_t)(y + line) * (size_t)dst.stride + (size_t)(x + from) * 4,
		       tile + (size_t)line * (size_t)atlas.cw * 4 + (size_t)from * 4,
		       (size_t)(to - from) * 4);
}

tr_rect tr_grid_blit(const int32_t *grid, int cols, int rows, tr_atlas atlas, tr_surface dst, int x, int y)
{
	const size_t tile_bytes = (size_t)atlas.ch * (size_t)atlas.cw * 4;
	int r0 = rows, r1 = -1, c0 = cols, c1 = -1;
	for (int r = 0; r < rows; r++)
		for (int c = 0; c < cols; c++) {
			const int32_t t = grid[r * cols + c];
			if (!t)
				continue;
			r0 = tr_min(r0, r);
			r1 = tr_max(r1, r);
			c0 = tr_min(c0, c);
			c1 = tr_max(c1, c);
			blit_tile(atlas.px + (size_t)t * tile_bytes, atlas, dst, x + c * atlas.cw, y + r * atlas.ch);
		}
	if (r1 < 0)
		return (tr_rect){ 0, 0, 0, 0 };
	const tr_rect touched = { y + r0 * atlas.ch, y + (r1 + 1) * atlas.ch,
	                          x + c0 * atlas.cw, x + (c1 + 1) * atlas.cw };
	return tr_rect_clip(touched, dst);
}

tr_rect tr_mesh_draw(tr_mesh mesh, const float r[9], tr_view view, tr_atlas atlas,
                     tr_surface dst, int x, int y)
{
	int32_t grid[TR_MESH_MAX_CELLS];
	if (tr_mesh_grid(mesh, r, view, grid) < 0)
		return (tr_rect){ 0, 0, 0, 0 };
	return tr_grid_blit(grid, view.cols, view.rows, atlas, dst, x, y);
}
