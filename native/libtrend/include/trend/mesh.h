/* 3D objects drawn as shaded ASCII cells: rotate, cull back faces, project, depth-test, shade,
 * then copy each cell's pre-rendered tile into a surface. */
#ifndef TREND_MESH_H
#define TREND_MESH_H

#include <stdint.h>

#include "trend/types.h"

#define TR_MESH_MAX_CELLS 4096         /* rows * cols upper bound */

/* Sampled surface points grouped into faces; face f owns points fstart[f] .. fstart[f + 1] - 1. */
typedef struct {
	const float *pts;              /* n_points x 3 */
	const int32_t *fstart;         /* nfaces + 1 */
	const float *fnrm, *fcen;      /* nfaces x 3: face normal, face centre */
	const int32_t *fcol;           /* nfaces: palette colour index */
	int nfaces;
} tr_mesh;

/* Projection into a cols x rows cell grid. */
typedef struct {
	float k, aspect, cam_z;
	float light[3];
	int cols, rows, shades;
} tr_view;

/* Pre-rendered cells: px is [n_tiles][ch][cw][4] RGBX. */
typedef struct {
	const uint8_t *px;
	int ch, cw;
} tr_atlas;

/* Writes the rows x cols tile grid (colour * shades + 1 + shade, 0 = empty) and returns the number
 * of points drawn, or -1 if the grid exceeds TR_MESH_MAX_CELLS. r is a row-major 3x3 rotation. */
int tr_mesh_grid(tr_mesh mesh, const float r[9], tr_view view, int32_t *grid);

/* Copies the tile of every non-empty cell into dst with the grid's top-left at (x, y). Clipped;
 * empty cells leave dst untouched. Returns the rectangle written. */
tr_rect tr_grid_blit(const int32_t *grid, int cols, int rows, tr_atlas atlas, tr_surface dst, int x, int y);

/* tr_mesh_grid followed by tr_grid_blit. */
tr_rect tr_mesh_draw(tr_mesh mesh, const float r[9], tr_view view, tr_atlas atlas,
                     tr_surface dst, int x, int y);

#endif
