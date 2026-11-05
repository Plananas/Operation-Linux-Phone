/* The Music app's screen and touch handling. Playback is native/player/, which fills in the status
 * and library declared here.
 *
 * tr_music holds only what the screen remembers (scroll position, what's being touched), and is
 * opaque: allocate tr_music_size() bytes. Everything that changes the state takes it as in and writes
 * the next state to out, which may be the same pointer. Touches and keys don't start anything
 * themselves: they return a command for the player. tr_music_render is a pure function of its inputs.
 */
#ifndef TREND_APPS_MUSIC_H
#define TREND_APPS_MUSIC_H

#include <stddef.h>
#include <stdint.h>

#include "trend/draw.h"
#include "trend/mesh.h"
#include "trend/types.h"

typedef struct tr_music tr_music;
typedef struct tr_music_viz tr_music_viz;

enum {
	TR_MUSIC_MAX_TRACKS = 512,
	TR_MUSIC_NAME = 72,            /* Latin-1, ready to draw */
	TR_MUSIC_SCOPE = 216,          /* samples in the visualiser */
	TR_MUSIC_VOLUME_MAX = 15,
	TR_MUSIC_ELLIPSIS = 0x85,      /* a slot the font table maps to U+2026 */
};

typedef enum { TR_PLAYER_STOPPED, TR_PLAYER_PLAYING, TR_PLAYER_PAUSED } tr_player_state;
typedef enum { TR_OUTPUT_SPEAKER, TR_OUTPUT_HEADPHONES, TR_OUTPUT_BLUETOOTH } tr_output;

/* What the player is doing right now. */
typedef struct {
	int state;                     /* tr_player_state */
	int track;                     /* index into the library, or -1 */
	int output;                    /* tr_output */
	int volume;                    /* 0 .. TR_MUSIC_VOLUME_MAX */
	int n_tracks;
	double position, duration;     /* seconds; duration 0 = unknown */
	char title[TR_MUSIC_NAME], artist[TR_MUSIC_NAME], error[TR_MUSIC_NAME];
	int16_t scope[TR_MUSIC_SCOPE];
} tr_music_status;

/* The tracks found, as display names. version changes whenever the list does. */
typedef struct {
	unsigned version;
	int n;
	char names[TR_MUSIC_MAX_TRACKS][TR_MUSIC_NAME];
} tr_music_library;

typedef enum {
	TR_CMD_NONE,
	TR_CMD_PLAY_TRACK,             /* arg: track index */
	TR_CMD_TOGGLE,                 /* play or pause */
	TR_CMD_NEXT,
	TR_CMD_PREV,                   /* start of this track, or the previous one if near its start */
	TR_CMD_SEEK,                   /* arg: position in thousandths of the track */
	TR_CMD_VOLUME,                 /* arg: the level, 0 .. TR_MUSIC_VOLUME_MAX */
	TR_CMD_RESCAN,                 /* look for new files */
	TR_CMD_RELEASE,                /* pause and let go of the audio device, for an alarm or the radio */
} tr_music_cmd_kind;

typedef struct {
	int kind;                      /* tr_music_cmd_kind */
	int arg;
} tr_music_cmd;

typedef struct {
	const tr_glyph *font16, *font17, *font22, *font25;
	tr_colour accent, error;
	tr_atlas atlas;                /* the home screen icons' shaded characters, for the visualiser */
	int shades;                    /* characters per colour in the atlas */
} tr_music_theme;

size_t tr_music_size(void);
size_t tr_music_status_size(void);
size_t tr_music_library_size(void);

void tr_music_init(tr_music *out);

/* A status for when no player is running; error may be NULL. */
void tr_music_status_init(tr_music_status *out, const char *error);

/* A touch in app-area coordinates (y = 0 is the top of the app area). event is TR_MUSIC_DOWN etc. */
enum { TR_MUSIC_DOWN, TR_MUSIC_MOVE, TR_MUSIC_UP };
tr_music_cmd tr_music_touch(const tr_music *in, tr_music *out, const tr_music_status *status, int event, int x, int y);


/* Keep the playing track in view when it changes by itself. */
void tr_music_follow(const tr_music *in, tr_music *out, const tr_music_status *status);

/* Changes whenever the screen needs redrawing; stable unless music is playing. */
uint64_t tr_music_frame_key(const tr_music *s, const tr_music_status *status, double now);

/* Draw the whole app area, on whichever tab is showing. */
void tr_music_render(const tr_music *s, const tr_music_status *status, const tr_music_library *library,
		     const tr_music_viz *viz, const tr_music_theme *theme, tr_surface dst);

/* The visualiser tab. Its state remembers the last few moments of music: allocate
 * tr_music_viz_size() bytes. Advancing updates it in place: it moves on as time passes, however often
 * it's called, and holds still while paused. Drawing fills dst with the picture. */
int tr_music_showing_viz(const tr_music *s);
size_t tr_music_viz_size(void);
void tr_music_viz_init(tr_music_viz *out);
void tr_music_viz_advance(tr_music_viz *v, const tr_music_status *status, double now);
void tr_music_viz_draw(const tr_music_viz *v, const tr_music_theme *theme, tr_surface dst);

/* Text for the screen, shared with the player. Both always terminate out. */

/* UTF-8 to the font's Latin-1. Common typographic punctuation is simplified and anything else
 * outside Latin-1 becomes '?'. */
void tr_music_latin1(const char *utf8, char *out, size_t cap);

/* "/data/music/Some_Band/01_song.mp3" becomes "01 song". */
void tr_music_display_name(const char *path, char *out, size_t cap);

#endif
