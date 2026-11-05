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
	int pressed_row;               /* row of the list, or -1 */
	int pressed_back;
	int pressed_tab;               /* 0 song, 1 visualiser, or -1 */
	int drag;
	int moved;                     /* a list touch has become a scroll */
	int touch_y, scroll_at_touch;
	int scroll;                    /* pixels the list has scrolled by */
	int folder;                    /* the open folder in the library; 0 is the top level */
	int top_scroll;                /* where the top level was when a folder opened */
	unsigned library_version;      /* the library the two above were last checked against */
	char folder_name[TR_MUSIC_NAME];       /* finds the open folder again when the library changes */
	int seek_x;                    /* where the seek handle is while dragging */
	int showing_viz;
	int followed_track;            /* the playing track last time we looked */
	unsigned version;              /* bumped by any change the screen shows */
};

/* The rows of the list: at the top level, the folders and then the tracks not in one. In a folder, a
 * row stays above the list to go back, and the list is that folder's tracks. */
typedef struct {
	int n_folders, first_track, n_tracks;
} music_rows;

static inline music_rows music_rows_of(const tr_music *s, const tr_music_library *library)
{
	if (library->n_folders == 0)
		return (music_rows){ 0, 0, 0 };
	const tr_music_folder *f = &library->folders[s->folder];
	return (music_rows){ s->folder ? 0 : library->n_folders - 1, f->first, f->n };
}

static inline int music_rows_y0(const tr_music *s)
{
	return s->folder ? ROWS_Y0 + ROW_H : ROWS_Y0;
}

/* The row that shows a track: its own, or its folder's from the top level. -1 if neither is showing. */
static inline int music_row_of_track(const tr_music *s, const tr_music_library *library, int track)
{
	const int folder = tr_music_folder_of(library, track);
	if (folder < 0)
		return -1;
	if (folder == s->folder) {
		const music_rows rows = music_rows_of(s, library);
		return rows.n_folders + track - rows.first_track;
	}
	return s->folder == 0 ? folder - 1 : -1;
}

#endif
