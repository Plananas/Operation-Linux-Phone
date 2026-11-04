/* The Web app's screen: a chat with an AI agent, and a browser behind it. All the network and parsing is in
 * native/webd/, which runs twice as an unprivileged program. This part draws what webd sends and turns touches
 * into commands; Python passes them across.
 *
 * Both tabs show the same thing: a document of rows on a character grid (trend/apps/web_wire.h). The status holds
 * both documents. It's big, about 2 MB, so allocate it as untouched memory: only the rows in use cost anything.
 * Everything read from webd is treated as hostile.
 */
#ifndef TREND_APPS_WEB_H
#define TREND_APPS_WEB_H

#include <stddef.h>
#include <stdint.h>

#include "trend/apps/web_wire.h"
#include "trend/draw.h"
#include "trend/mesh.h"
#include "trend/types.h"

typedef struct tr_web tr_web;
typedef struct tr_web_status tr_web_status;

enum { TR_WEB_CHAT, TR_WEB_PAGE };
enum { TR_WEB_DOWN, TR_WEB_MOVE, TR_WEB_UP };

enum {
	TR_WEB_NONE, TR_WEB_LINK, TR_WEB_FIELD, TR_WEB_INPUT, TR_WEB_NEW_CHAT, TR_WEB_STOP_CHAT,
	TR_WEB_BACK, TR_WEB_FORWARD, TR_WEB_RELOAD, TR_WEB_STOP_PAGE,
};

typedef struct {
	int kind, arg;
} tr_web_cmd;

/* Where the keyboard starts, in app-area pixels: Python lays it over the screen there. */
enum { TR_WEB_KEYBOARD_Y = 464 };

typedef struct {
	const tr_glyph *font16, *font19, *font25;
	tr_colour accent, error;
	tr_mesh globe;
	tr_view small_view, big_view;  /* a strip at the top of the chat, and the middle of an empty screen */
	tr_atlas atlas;                /* the icons' tiles: pictures use them too */
} tr_web_theme;

size_t tr_web_size(void);
size_t tr_web_status_size(void);
void tr_web_init(tr_web *out);
void tr_web_status_init(tr_web_status *out);

/* What a webd printed: any number of bytes, cut anywhere. which is TR_WEB_CHAT or TR_WEB_PAGE. */
void tr_web_feed(tr_web_status *st, int which, const uint8_t *data, size_t n);

/* A URL webd asked to have opened, or "". Copy it, then clear it. */
const char *tr_web_peek_open(const tr_web_status *st);
void tr_web_clear_open(tr_web_status *st);
const char *tr_web_address(const tr_web_status *st);

/* A touch in app-area coordinates. */
tr_web_cmd tr_web_touch(const tr_web *in, tr_web *out, const tr_web_status *st, int event, int x, int y, double now);

int tr_web_tab(const tr_web *s);
void tr_web_set_tab(tr_web *s, int tab);
int tr_web_scroll_of(const tr_web *s, int tab);

/* The text being typed, shown above the keyboard. NULL: not typing. */
void tr_web_set_compose(tr_web *s, const char *text, const char *label);

/* Move on to time now (flings, following the chat) and return a key that changes when a redraw is needed. */
uint64_t tr_web_advance(tr_web *s, const tr_web_status *st, double now);

/* Draw the whole app area. */
void tr_web_render(const tr_web *s, const tr_web_status *st, const tr_web_theme *theme, double now, tr_surface dst);

#endif
