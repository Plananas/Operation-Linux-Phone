/* Private to the Files app: its state, what it knows about the server, and its layout. */
#ifndef FILES_STATE_H
#define FILES_STATE_H

#include "trend/apps/files.h"

enum {
	FILES_SLOTS = 5, FILES_NAME = 64, FILES_REASON = 96, FILES_ADDRESS = 48, FILES_LINE = 512,
	/* in app-area pixels */
	CARD_X0 = 12, CARD_X1 = 468,
	SHARE_Y0 = TR_FILES_CARD_Y0, SHARE_Y1 = 286,
	ACTIVITY_Y0 = 306, ACTIVITY_Y1 = 596, ROWS_Y0 = 322, ROW_H = 52,
	FREE_Y = 604,
	KEY_X0 = 28, KEY_X1 = 452, KEY_Y0 = 634, KEY_Y1 = 716,
};

typedef struct {
	int used, sending, active, failed;
	int64_t done, total;
	char name[FILES_NAME];         /* Latin-1, ready for the font */
} files_xfer;

/* Everything on screen. A change here is what makes a redraw. */
typedef struct {
	int phase, port;
	int64_t free_bytes;            /* -1 until the server has said */
	char pin[8];
	char address[FILES_ADDRESS];
	char reason[FILES_REASON];
	files_xfer xfers[FILES_SLOTS];
} files_shown;

struct tr_files_status {
	files_shown shown;
	unsigned version;
	size_t line_len;               /* a line still arriving */
	int line_too_long;
	char line[FILES_LINE];
};

struct tr_files {
	int pressed;
};

#endif
