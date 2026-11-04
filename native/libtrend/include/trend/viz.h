/* Audio visualisers: a phosphor oscilloscope and a perspective spectrum terrain. */
#ifndef TREND_VIZ_H
#define TREND_VIZ_H

#include <stdint.h>

#include "trend/mesh.h"
#include "trend/types.h"

/* The scope's inputs. samples is NULL when there is no live audio: a flat line is drawn at
 * idle_level. floor is the graticule, the minimum brightness of every pixel. lut maps a phosphor
 * intensity to a colour. */
typedef struct {
	const int16_t *samples;
	int n_samples;
	const uint8_t *floor;
	const uint32_t *lut;
	int idle_level;
} tr_scope;

/* Advance the scope one frame: decay phos (h x w intensities), draw the trace into it, and paint
 * it into dst at (x, y). Returns the auto-gain peak to pass in next frame. */
float tr_scope_frame(uint8_t *phos, int h, int w, tr_scope scope, float peak,
                     tr_surface dst, int x, int y);

/* Fixed geometry of the terrain, one entry per (ridge, column) unless noted. Ridge 0 is the front. */
typedef struct {
	const int32_t *band;           /* band index; samples band and band + 1 */
	const float *blend;            /* weight of band + 1 */
	const float *base, *amp;       /* ridge baseline and height scale, in rows */
	const uint8_t *visible;        /* inside this ridge's perspective width? */
	const int32_t *colour;         /* per ridge: first atlas index of its colour */
	const float *dim;              /* per ridge: brightness falloff with depth */
	int ridges, cols, rows, shades;
} tr_terrain;

/* Draw history (ridges x cols levels, 0..1) as ridges of shaded cells, nearer ridges hiding farther
 * ones, painting every cell at (x, y). atlas tile 0 is the empty background. */
void tr_terrain_draw(tr_terrain t, const float *history, tr_atlas atlas, tr_surface dst, int x, int y);

/* A flat tape wrapped round a drum. Each screen column reads the tape through a pre-filtered copy
 * ("mip") whose width matches how much tape lies behind that column. */
typedef struct {
	const uint8_t *mips;           /* [n_mips][rows][tape_w] tape intensity */
	const uint16_t *key;           /* rows x cols: per pixel, the high bits of the lut index */
	const uint32_t *lut;           /* key | intensity -> pixel */
	const double *offset;          /* cols: tape position at each column, relative to the centre */
	const int32_t *mip_of_col;     /* cols */
	double tape_start, px_per_unit;
	int rows, cols, tape_w;
} tr_dial;

/* Paint the drum into dst at (x, y), turned to position. */
void tr_dial_draw(tr_dial d, double position, tr_surface dst, int x, int y);

#endif
