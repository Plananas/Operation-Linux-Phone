/* Private to the Music app: the state and the layout both music.c and music_view.c need. */
#ifndef MUSIC_STATE_H
#define MUSIC_STATE_H

#include "trend/apps/music.h"

enum {
	/* in app-area pixels */
	CARD_X0 = 12, CARD_X1 = 468,
	NOW_Y0 = 14, NOW_Y1 = 340,
	TITLE_Y = 28, ARTIST_Y = 60,
	SCOPE_X = 24, SCOPE_Y0 = 90, SCOPE_Y1 = 186, SCOPE_STEP = 2,
	BAR_X0 = 28, BAR_X1 = 452, BAR_Y0 = 198, BAR_Y1 = 208, BAR_HIT_Y0 = 186, BAR_HIT_Y1 = 240,
	TIME_Y = 214,
	KEY_X0 = 28, KEY_W = 136, KEY_GAP = 8, KEY_Y0 = 250, KEY_Y1 = 326, N_KEYS = 3,
	LIST_Y0 = 356, LIST_Y1 = 724, ROWS_Y0 = 366, ROW_H = 44, N_ROWS = 8,
	ROWS_Y1 = ROWS_Y0 + N_ROWS * ROW_H,
	ROWS_X0 = 18, ROWS_X1 = 462,
};

enum { KEY_PREV, KEY_PLAY, KEY_NEXT };
enum { DRAG_NONE, DRAG_LIST, DRAG_SEEK };

struct tr_music {
	int pressed_key;               /* or -1 */
	int pressed_row;               /* track index, or -1 */
	int drag;
	int moved;                     /* a list touch has become a scroll */
	int touch_y, scroll_at_touch;
	int scroll;                    /* pixels the list has scrolled by */
	int seek_x;                    /* where the seek handle is while dragging */
	int followed_track;            /* the playing track last time we looked */
	unsigned version;              /* bumped by any change the screen shows */
};

#endif
