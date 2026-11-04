/* Private to the calculator: the state, its layout, and what the screen derives from it. */
#ifndef CALCULATOR_STATE_H
#define CALCULATOR_STATE_H

#include "trend/apps/calculator.h"

enum {
	CALC_ROWS = 5, CALC_COLS = 4, CALC_KEYS = CALC_ROWS * CALC_COLS,
	CALC_EXPR_MAX = 64,
	CALC_PRETTY_MAX = CALC_EXPR_MAX * 3 + 1,
	CALC_RESULT_MAX = 32,
	CALC_HISTORY = 3,
	CALC_HIST_LINES = 2,
	CALC_HIST_LINE_MAX = 40,
	CALC_LINE_EXPR_MAX = 32,
	CALC_LINE_TEXT_MAX = CALC_EXPR_MAX + 3,
	/* keypad and display layout, in app-area pixels */
	KEY_X = 14, KEY_Y = 238, KEY_W = 108, KEY_H = 92, KEY_GAP_X = 8, KEY_GAP_Y = 7,
	DISP_X0 = 14, DISP_Y0 = 14, DISP_X1 = 466, DISP_Y1 = 222,
};

#define CALC_FADE 0.30
#define CALC_BLINK 0.53

typedef enum { TONE_PREVIEW, TONE_ACCENT, TONE_ERROR } calc_tone;

/* The text on the prompt and result lines. */
typedef struct {
	char expr[CALC_LINE_EXPR_MAX];
	char text[CALC_LINE_TEXT_MAX];
	calc_tone tone;
	int size;
} calc_lines;

typedef struct {
	char expr[CALC_PRETTY_MAX];
	char result[CALC_RESULT_MAX];
} calc_entry;

typedef struct {
	char line[CALC_HIST_LINES][CALC_HIST_LINE_MAX];
	int n;
} calc_hist_lines;

struct tr_calc {
	char expr[CALC_EXPR_MAX];
	char shown_expr[CALC_PRETTY_MAX];      /* what the prompt shows after "=" */
	int just_eq;
	int pressed;                           /* key index, or -1 */
	calc_entry history[CALC_HISTORY];
	int n_history;
	double released[CALC_KEYS];            /* when each key was let go, or -1 */
	double anim_until;
	double t_type, t_eq, t_err, t_clear, t_scroll;
	calc_lines cleared;                    /* the line being dissolved by "C" */
	calc_hist_lines scroll_from;           /* history lines before the scroll */
};

extern const unsigned char CALC_KEYCODES[CALC_KEYS];

calc_lines calc_lines_of(const tr_calc *s);
calc_hist_lines calc_hist_lines_of(const tr_calc *s);

/* Bounded string building: dst always ends up terminated. */
static inline void calc_append(char *dst, size_t cap, const char *src)
{
	size_t n = 0;
	while (n < cap && dst[n])
		n++;
	while (n + 1 < cap && *src)
		dst[n++] = *src++;
	if (n < cap)
		dst[n] = '\0';
}

static inline void calc_copy(char *dst, size_t cap, const char *src)
{
	dst[0] = '\0';
	calc_append(dst, cap, src);
}

#endif
