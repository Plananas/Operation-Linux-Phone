/* Private to the Web app: its state, what it knows from webd, and its layout. */
#ifndef WEB_STATE_H
#define WEB_STATE_H

#include "trend/apps/web.h"

enum {
	WEB_SLOTS = 2, WEB_ADDR_MAX = 128, WEB_STATUS_MAX = 96, WEB_OPEN_MAX = 2048, WEB_COMPOSE_MAX = 1024,
	WEB_FRAME_MAX = WEB_OPEN_MAX + 8,
	/* in app-area pixels */
	TAB_Y1 = 44, TAB_CHAT_X0 = 8, TAB_CHAT_X1 = 88, TAB_PAGE_X0 = 94, TAB_PAGE_X1 = 174,
	KEYS_Y1 = 44, KEY_W = 58, KEYS_X1 = 472,
	ORB_Y0 = 48, ORB_Y1 = 220, ADDR_Y0 = 48, ADDR_Y1 = 78,
	INPUT_Y0 = 672, INPUT_Y1 = 728, INPUT_X0 = 10, INPUT_X1 = 470,
	CONTENT_Y1 = 668,
	COMPOSE_Y0 = 342, COMPOSE_Y1 = TR_WEB_KEYBOARD_Y - 6,
	TAP_SLOP = 14,
};

typedef struct {
	uint8_t len;
	uint8_t b[WEB_ROW_BYTES];
} web_row;

typedef struct {
	int n_rows;
	int state;                     /* WEB_IDLE... */
	int secure;
	unsigned scroll_seq, scroll_to;
	char addr[WEB_ADDR_MAX];
	char status[WEB_STATUS_MAX];
	/* a frame on its way in */
	uint8_t head[4];
	int head_n;
	size_t want, have;
	uint8_t frame[WEB_FRAME_MAX];
	web_row rows[WEB_MAX_ROWS];
} web_doc;

struct tr_web_status {
	unsigned version;
	char open_url[WEB_OPEN_MAX];
	web_doc docs[WEB_SLOTS];
};

struct tr_web {
	int tab;
	double scroll[WEB_SLOTS];
	double velocity;
	int follow;                    /* stick to the bottom of the chat */
	unsigned seen_scroll[WEB_SLOTS];
	double last_advance;

	/* The chat is written out as Blip says it. Rows before reveal_row are all showing and reveal_cells of that row
	 * are; the rest of it and everything after are still to come. Time left over waits in reveal_budget, counted
	 * in characters, and a pause is just that going below zero. */
	int reveal_row, reveal_cells;
	double reveal_budget;
	double talk_until;             /* the mascot talks until then */

	/* the touch in progress */
	int down, moved, pressed;
	int touch_y, touch_x;
	double scroll_at_touch, last_y, last_t, touch_velocity;

	int composing;
	unsigned compose_version;
	char compose[WEB_COMPOSE_MAX];
	char compose_label[48];
};

enum { PRESS_NONE, PRESS_TAB_CHAT, PRESS_TAB_PAGE, PRESS_INPUT, PRESS_KEY0 };

int web_content_y(int tab);

/* How many rows of tab there are to see: on the chat, not the ones Blip hasn't got to. */
int web_rows_showing(const tr_web *s, const tr_web_status *st, int tab);
/* How many of the cells in row i of tab to draw. */
int web_cells_showing(const tr_web *s, const web_doc *d, int tab, int i);

#endif
