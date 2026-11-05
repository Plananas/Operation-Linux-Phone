/* What webd says to the Web app, down a pipe. Shared by native/webd/ and libtrend, so that it needs nothing
 * else from either.
 *
 * A frame is one kind byte, a 3-byte little-endian payload length, then the payload. The reader must not
 * trust any of it: webd parses the internet, so it could be compromised.
 *
 * A document is rows of a fixed-width character grid. A row is either text with control bytes mixed in, or a
 * strip of ASCII art.
 */
#ifndef TREND_APPS_WEB_WIRE_H
#define TREND_APPS_WEB_WIRE_H

enum {
	WEB_F_RESET = 1,               /* forget the rows */
	WEB_F_ROW,                     /* u16 index, then the row's bytes */
	WEB_F_ROWS,                    /* u16 count: drop any rows past it */
	WEB_F_ADDR,                    /* u8 secure, then the address to show */
	WEB_F_STATUS,                  /* u8 WEB_IDLE/WEB_BACKGROUND/WEB_BUSY, then text */
	WEB_F_SCROLL,                  /* u32 pixels: scroll here */
	WEB_F_OPEN,                    /* a URL to open in the browser */
};

enum { WEB_IDLE, WEB_BACKGROUND, WEB_BUSY };

/* The agent's status while its answer is coming in: the mascot talks along. */
#define WEB_REPLYING "Here's what I've got:"

enum {
	WEB_COLS = 46,                 /* text cells across */
	WEB_ADVANCE = 10, WEB_ROW_H = 24, WEB_MARGIN = 10,
	WEB_MAX_ROWS = 8192,
	WEB_ROW_BYTES = 127,           /* most a row may hold */
	WEB_ART_COLS = 60, WEB_ART_ROWS = 2,     /* one art row is two strips of 8 x 12 tiles, the icons' cells */
	WEB_SHADES = 13, WEB_PALETTE = 10,
};

/* Bytes below 0x20 in a text row. */
enum {
	WEB_S_NORMAL = 1, WEB_S_HEAD, WEB_S_BOLD, WEB_S_DIM, WEB_S_USER, WEB_S_ERROR,
	WEB_C_LINK = 0x0e,             /* followed by a u16 target id, big-endian */
	WEB_C_END = 0x0f,              /* end of a link or field */
	WEB_C_FIELD = 0x10,            /* followed by a u16 field id, big-endian */
};

#define WEB_ART_MARK 0x7f              /* first byte of an art row; then 2 * WEB_ART_COLS tile numbers */

#endif
