/* The Files app: the screen that goes with filesd (native/filesd/), the web server that lets a browser
 * on the home network add and fetch files.
 *
 * This part only draws and turns touches into commands. Python starts and stops the server, and hands
 * over what it prints. Its output is text, one fact per line, repeated whole whenever anything changes:
 *
 *   U <pin> <port>                                 it's up
 *   A <address>                                    where to reach it (empty: no network)
 *   F <bytes>                                      free disk space
 *   T <slot> <u|d> <a|k|x> <done> <total> <name>   a transfer: up or down; active, ok or failed
 *   X <reason>                                     why it stopped, if it wasn't asked to
 *
 * The state and status are opaque: allocate the sizes given below. tr_files_render is a pure function
 * of them.
 */
#ifndef TREND_APPS_FILES_H
#define TREND_APPS_FILES_H

#include <stddef.h>
#include <stdint.h>

#include "trend/draw.h"
#include "trend/mesh.h"
#include "trend/types.h"

typedef struct tr_files tr_files;
typedef struct tr_files_status tr_files_status;

enum { TR_FILES_OFF, TR_FILES_STARTING, TR_FILES_ON };
enum { TR_FILES_DOWN, TR_FILES_MOVE, TR_FILES_UP };
enum { TR_FILES_NONE, TR_FILES_START, TR_FILES_STOP };

#define TR_FILES_ELLIPSIS 0x85u        /* a slot the font table maps to U+2026 */

/* Where the turning folder sits, in app-area pixels and character cells. The atlas needs the same
 * numbers, to match the card's scanlines behind the folder. */
enum { TR_FILES_CARD_Y0 = 16, TR_FILES_ICON_X = 300, TR_FILES_ICON_Y = 124, TR_FILES_ICON_COLS = 19, TR_FILES_ICON_ROWS = 12 };

typedef struct {
	const tr_glyph *font16, *font17, *font22, *font25, *font54;
	tr_colour accent, error;
	tr_mesh icon;                  /* the app's folder */
	tr_view view;
	tr_atlas atlas;
} tr_files_theme;

size_t tr_files_size(void);
size_t tr_files_status_size(void);
void tr_files_init(tr_files *out);
void tr_files_status_init(tr_files_status *out);

/* What the server printed: any number of bytes, cut anywhere. */
void tr_files_feed(tr_files_status *st, const char *data, size_t n);

/* TR_FILES_STARTING clears the last run. TR_FILES_OFF keeps its transfers on show. message says why
 * it's off, and NULL keeps whatever reason the server gave. */
void tr_files_set_phase(tr_files_status *st, int phase, const char *message);
int tr_files_phase(const tr_files_status *st);
const char *tr_files_pin(const tr_files_status *st);

/* A touch in app-area coordinates. Returns TR_FILES_START, _STOP or _NONE. */
int tr_files_touch(const tr_files *in, tr_files *out, const tr_files_status *st, int event, int x, int y);

/* Changes whenever the screen needs redrawing; stable unless something is being transferred. */
uint64_t tr_files_frame_key(const tr_files *s, const tr_files_status *st, double now);

/* Draw the whole app area. */
void tr_files_render(const tr_files *s, const tr_files_status *st, const tr_files_theme *theme, double now, tr_surface dst);

/* A byte count for people: "812 B", "3.4 MB". */
void tr_files_format_size(int64_t bytes, char *out, size_t cap);

#endif
