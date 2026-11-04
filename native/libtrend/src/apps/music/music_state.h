/* Private to the Music app: the state and the layout both music.c and music_view.c need. */
#ifndef MUSIC_STATE_H
#define MUSIC_STATE_H

#include "trend/apps/music.h"

enum {
	/* in app-area pixels */
	TAB_Y0 = 8, TAB_Y1 = 52, TAB_X0 = 14, TAB_X1 = 466, TAB_MID = 240,
	CARD_X0 = 12, CARD_X1 = 468,
	BAR_X0 = 28, BAR_X1 = 452, BAR_H = 10,
	KEY_X0 = 28, KEY_W = 136, KEY_GAP = 8, KEY_H = 76, N_KEYS = 3,
	/* the song tab */
	NOW_Y0 = 60, NOW_Y1 = 386,
	SCOPE_X = 24, SCOPE_Y0 = 136, SCOPE_Y1 = 232, SCOPE_STEP = 2,
	LIST_Y0 = 402, LIST_Y1 = 724, ROWS_Y0 = 412, ROW_H = 44, N_ROWS = 7,
	ROWS_Y1 = ROWS_Y0 + N_ROWS * ROW_H,
	ROWS_X0 = 18, ROWS_X1 = 462,
	/* the visualiser tab */
	PICTURE_Y0 = 58, PICTURE_Y1 = 520,
};

enum { KEY_PREV, KEY_PLAY, KEY_NEXT };
enum { DRAG_NONE, DRAG_LIST, DRAG_SEEK };

/* The title, seek bar and keys are on both tabs, in different places. */
typedef struct {
	int title_y, artist_y, bar_y0, time_y, key_y0;
} music_layout;

static inline music_layout music_layout_of(int showing_viz)
{
	return showing_viz ? (music_layout){ 530, 562, 588, 604, 642 }
			   : (music_layout){ 74, 106, 244, 260, 296 };
}

struct tr_music {
	int pressed_key;               /* or -1 */
	int pressed_row;               /* track index, or -1 */
	int pressed_tab;               /* 0 song, 1 visualiser, or -1 */
	int drag;
	int moved;                     /* a list touch has become a scroll */
	int touch_y, scroll_at_touch;
	int scroll;                    /* pixels the list has scrolled by */
	int seek_x;                    /* where the seek handle is while dragging */
	int showing_viz;
	int followed_track;            /* the playing track last time we looked */
	unsigned version;              /* bumped by any change the screen shows */
};

#endif
