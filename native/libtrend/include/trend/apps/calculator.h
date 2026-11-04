/* The Calculator app. Its state is opaque: allocate tr_calc_size() bytes and pass them around.
 *
 * Every function that changes the state takes it as in and writes the next state to out, which may
 * be the same pointer. tr_calc_render is a pure function of the state and the time, so nothing needs
 * caching between frames.
 */
#ifndef TREND_APPS_CALCULATOR_H
#define TREND_APPS_CALCULATOR_H

#include <stddef.h>
#include <stdint.h>

#include "trend/draw.h"
#include "trend/types.h"

typedef struct tr_calc tr_calc;

enum { TR_TOUCH_DOWN, TR_TOUCH_MOVE, TR_TOUCH_UP };

/* Key codes are bytes in the font encoding. These three are not ASCII. */
#define TR_CALC_DIV 0xF7u              /* Latin-1 division sign */
#define TR_CALC_MUL 0xD7u              /* Latin-1 multiplication sign */
#define TR_CALC_MINUS 0x96u            /* a slot the font table maps to U+2212 */
#define TR_CALC_ELLIPSIS 0x85u         /* a slot the font table maps to U+2026 */
#define TR_CALC_DEL 'D'

/* The fonts and system colours the screen is drawn with. */
typedef struct {
	const tr_glyph *font16, *font17, *font22, *font25, *font32, *font34, *font54;
	const char *shades;            /* ASCII shading ramp; index 0 is the empty cell */
	int n_shades;
	tr_colour accent, error;
} tr_calc_theme;

size_t tr_calc_size(void);

void tr_calc_init(tr_calc *out);

/* A touch in app-area coordinates (y = 0 is the top of the app area). */
void tr_calc_touch(const tr_calc *in, tr_calc *out, int event, int x, int y, double now);

/* A key press, as if tapped. */
void tr_calc_press(const tr_calc *in, tr_calc *out, unsigned key, double now);

/* Changes whenever the screen needs redrawing; stable while idle. */
uint64_t tr_calc_frame_key(const tr_calc *s, double now);

/* Draw the whole app area. */
void tr_calc_render(const tr_calc *s, const tr_calc_theme *theme, double now, tr_surface dst);

/* The current expression or result, for tests. */
const char *tr_calc_expr(const tr_calc *s);

#endif
