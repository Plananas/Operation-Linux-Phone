/* Music behaviour: what touches and keys do to the screen, and what they ask the player for.
 * Drawing is in music_view.c. */
#include <stdio.h>
#include <string.h>

#include "music_state.h"

#define TAP_SLOP 10                    /* pixels a finger may wander and still be a tap */
#define PLAY_TICKS_PER_SECOND 20.0     /* how often the waveform redraws */
#define VIZ_TICKS_PER_SECOND 30.0      /* how often the visualiser does */

static const tr_music_cmd NO_CMD = { TR_CMD_NONE, 0 };

size_t tr_music_size(void) { return sizeof(tr_music); }
size_t tr_music_status_size(void) { return sizeof(tr_music_status); }
size_t tr_music_library_size(void) { return sizeof(tr_music_library); }

void tr_music_init(tr_music *out)
{
	memset(out, 0, sizeof(*out));
	out->pressed_key = out->pressed_row = out->pressed_tab = out->followed_track = -1;
}

int tr_music_showing_viz(const tr_music *s)
{
	return s->showing_viz;
}

void tr_music_status_init(tr_music_status *out, const char *error)
{
	memset(out, 0, sizeof(*out));
	out->track = -1;
	if (error)
		snprintf(out->error, sizeof(out->error), "%s", error);
}

/* ---- geometry ---- */

static int tab_at(int x, int y)
{
	if (y < TAB_Y0 || y >= TAB_Y1 || x < TAB_X0 || x >= TAB_X1)
		return -1;
	return x >= TAB_MID;
}

static int key_at(const tr_music *s, int x, int y)
{
	const int y0 = music_layout_of(s->showing_viz).key_y0;
	if (y < y0 || y >= y0 + KEY_H || x < KEY_X0)
		return -1;
	const int i = (x - KEY_X0) / (KEY_W + KEY_GAP);
	const int inside = (x - KEY_X0) % (KEY_W + KEY_GAP) < KEY_W;
	return i < N_KEYS && inside ? i : -1;
}

static int max_scroll(const tr_music *s, const tr_music_library *library)
{
	const music_rows rows = music_rows_of(s, library);
	return tr_max(0, (rows.n_folders + rows.n_tracks) * ROW_H - (ROWS_Y1 - music_rows_y0(s)));
}

static int row_at(const tr_music *s, const tr_music_library *library, int y)
{
	const int y0 = music_rows_y0(s);
	if (y < y0 || y >= ROWS_Y1)
		return -1;
	const music_rows rows = music_rows_of(s, library);
	const int i = (y - y0 + s->scroll) / ROW_H;
	return i < rows.n_folders + rows.n_tracks ? i : -1;
}

static int back_at(const tr_music *s, int y)
{
	return s->folder && !s->showing_viz && y >= ROWS_Y0 && y < ROWS_Y0 + ROW_H;
}

/* ---- moving around the library ---- */

/* The least scrolling that shows the row; a row of -1 only keeps the scroll in range. */
static void scroll_to_row(tr_music *s, const tr_music_library *library, int row)
{
	const int view = ROWS_Y1 - music_rows_y0(s);
	if (row >= 0) {
		const int top = row * ROW_H, bottom = top + ROW_H;
		if (top < s->scroll)
			s->scroll = top;
		else if (bottom > s->scroll + view)
			s->scroll = bottom - view;
	}
	s->scroll = tr_clamp(s->scroll, 0, max_scroll(s, library));
}

static void open_folder(tr_music *s, const tr_music_status *st, const tr_music_library *library, int folder)
{
	s->top_scroll = s->scroll;
	s->folder = folder;
	memcpy(s->folder_name, library->folders[folder].name, sizeof(s->folder_name));
	s->scroll = 0;
	scroll_to_row(s, library, st->track >= 0 ? music_row_of_track(s, library, st->track) : -1);
}

static void close_folder(tr_music *s, const tr_music_library *library)
{
	s->folder = 0;
	s->folder_name[0] = '\0';
	s->scroll = s->top_scroll;
	scroll_to_row(s, library, -1);
}

/* A rescan renumbers the folders, and may have removed the open one. */
static void find_open_folder(tr_music *s, const tr_music_library *library)
{
	if (s->folder) {
		s->folder = 0;
		for (int i = 1; i < library->n_folders && !s->folder; i++)
			if (!strcmp(library->folders[i].name, s->folder_name))
				s->folder = i;
		if (!s->folder)
			close_folder(s, library);
	}
	scroll_to_row(s, library, -1);
}

/* ---- touches ---- */

static int on_bar(const tr_music *s, int y)
{
	const music_layout l = music_layout_of(s->showing_viz);
	return y >= l.bar_y0 - 12 && y < l.time_y + 22;
}

static void touch_down(tr_music *s, const tr_music_status *st, const tr_music_library *library, int x, int y)
{
	s->touch_y = y;
	s->scroll_at_touch = s->scroll;
	s->moved = 0;
	s->pressed_tab = tab_at(x, y);
	s->pressed_key = key_at(s, x, y);
	s->pressed_row = -1;
	s->pressed_back = back_at(s, y);
	s->drag = DRAG_NONE;
	if (on_bar(s, y) && st->duration > 0.0) {
		s->drag = DRAG_SEEK;
		s->seek_x = tr_clamp(x, BAR_X0, BAR_X1);
	} else if (!s->showing_viz && !s->pressed_back && y >= ROWS_Y0 && y < ROWS_Y1) {
		s->drag = DRAG_LIST;
		s->pressed_row = row_at(s, library, y);
	}
}

static void touch_move(tr_music *s, const tr_music_library *library, int x, int y)
{
	if (s->pressed_tab >= 0 && tab_at(x, y) != s->pressed_tab)
		s->pressed_tab = -1;
	if (s->pressed_back && !back_at(s, y))
		s->pressed_back = 0;
	if (s->drag == DRAG_SEEK) {
		s->seek_x = tr_clamp(x, BAR_X0, BAR_X1);
	} else if (s->drag == DRAG_LIST) {
		const int dy = y - s->touch_y;
		if (dy > TAP_SLOP || dy < -TAP_SLOP)
			s->moved = 1;
		if (s->moved) {
			s->pressed_row = -1;
			s->scroll = tr_clamp(s->scroll_at_touch - dy, 0, max_scroll(s, library));
		}
	} else if (s->pressed_key >= 0 && key_at(s, x, y) != s->pressed_key) {
		s->pressed_key = -1;
	}
}

/* What a tap on a row does: open its folder, or play its track. */
static tr_music_cmd tap_row(tr_music *s, const tr_music_status *st, const tr_music_library *library, int row)
{
	const music_rows rows = music_rows_of(s, library);
	if (row >= rows.n_folders)
		return (tr_music_cmd){ TR_CMD_PLAY_TRACK, rows.first_track + row - rows.n_folders };
	open_folder(s, st, library, row + 1);
	return NO_CMD;
}

/* With nothing playing, the play and next keys start the open folder. */
static tr_music_cmd start_or(tr_music_cmd_kind kind, const tr_music *s, const tr_music_status *st, const tr_music_library *library)
{
	if (st->state == TR_PLAYER_STOPPED && s->folder)
		return (tr_music_cmd){ TR_CMD_PLAY_TRACK, music_rows_of(s, library).first_track };
	return (tr_music_cmd){ kind, 0 };
}

static tr_music_cmd touch_up(tr_music *s, const tr_music_status *st, const tr_music_library *library)
{
	tr_music_cmd cmd = NO_CMD;
	if (s->pressed_tab >= 0) {
		s->showing_viz = s->pressed_tab;
		s->pressed_tab = -1;
		return cmd;
	}
	if (s->drag == DRAG_SEEK) {
		cmd = (tr_music_cmd){ TR_CMD_SEEK, (s->seek_x - BAR_X0) * 1000 / (BAR_X1 - BAR_X0) };
	} else if (s->pressed_back) {
		close_folder(s, library);
	} else if (s->pressed_row >= 0) {
		cmd = tap_row(s, st, library, s->pressed_row);
	} else if (s->pressed_key == KEY_PREV) {
		cmd.kind = TR_CMD_PREV;
	} else if (s->pressed_key == KEY_PLAY) {
		cmd = start_or(TR_CMD_TOGGLE, s, st, library);
	} else if (s->pressed_key == KEY_NEXT) {
		cmd = start_or(TR_CMD_NEXT, s, st, library);
	}
	s->pressed_key = s->pressed_row = -1;
	s->pressed_back = 0;
	s->drag = DRAG_NONE;
	return cmd;
}

tr_music_cmd tr_music_touch(const tr_music *in, tr_music *out, const tr_music_status *status,
			    const tr_music_library *library, int event, int x, int y)
{
	tr_music next = *in;
	tr_music_cmd cmd = NO_CMD;
	if (event == TR_MUSIC_DOWN)
		touch_down(&next, status, library, x, y);
	else if (event == TR_MUSIC_MOVE)
		touch_move(&next, library, x, y);
	else
		cmd = touch_up(&next, status, library);
	next.version++;
	*out = next;
	return cmd;
}

void tr_music_follow(const tr_music *in, tr_music *out, const tr_music_status *status, const tr_music_library *library)
{
	tr_music next = *in;
	if (library->version != next.library_version) {
		next.library_version = library->version;
		find_open_folder(&next, library);
		next.version++;
	}
	if (status->track != next.followed_track) {
		next.followed_track = status->track;
		if (status->track >= 0 && next.drag == DRAG_NONE)
			scroll_to_row(&next, library, music_row_of_track(&next, library, status->track));
		next.version++;
	}
	*out = next;
}

/* ---- redraw key ---- */

static uint64_t mix_in(uint64_t h, uint64_t v)
{
	return (h ^ v) * 0x100000001b3ull;
}

static uint64_t mix_text(uint64_t h, const char *s)
{
	for (; *s; s++)
		h = mix_in(h, (unsigned char)*s);
	return h;
}

uint64_t tr_music_frame_key(const tr_music *s, const tr_music_status *st, double now)
{
	uint64_t h = 0xcbf29ce484222325ull;
	h = mix_in(h, s->version);
	h = mix_in(h, (uint64_t)st->state);
	h = mix_in(h, (uint64_t)(st->track + 1));
	h = mix_in(h, (uint64_t)st->output);
	h = mix_in(h, (uint64_t)st->volume);
	h = mix_in(h, (uint64_t)st->n_tracks);
	h = mix_in(h, (uint64_t)st->position);     /* whole seconds: the clock on a paused track after a seek */
	h = mix_in(h, (uint64_t)st->duration);
	h = mix_text(h, st->title);
	h = mix_text(h, st->artist);
	h = mix_text(h, st->error);
	/* The visualiser moves unless paused, and then it only needs an occasional redraw. */
	if (s->showing_viz)
		h = mix_in(h, (uint64_t)(now * (st->state == TR_PLAYER_PAUSED ? 1.0 : VIZ_TICKS_PER_SECOND)));
	else if (st->state == TR_PLAYER_PLAYING)
		h = mix_in(h, (uint64_t)(now * PLAY_TICKS_PER_SECOND));
	return h;
}
