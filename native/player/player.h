/* The music player: finds, decodes and plays audio files on its own thread, so playback carries on
 * while the app is closed or the screen is off.
 *
 * This is the one place in our C that holds state between calls, because playing audio is state.
 * It's a separate library from libtrend so that libtrend stays pure and the shell still starts if
 * this one or its dependencies (libsndfile, ALSA) are missing. Everything goes through the handle,
 * and all of these functions are safe to call from any thread.
 */
#ifndef TREND_PLAYER_H
#define TREND_PLAYER_H

#include "trend/apps/music.h"

typedef struct tr_player tr_player;

/* Start the player on the music in dir, creating dir if needed. It scans dir straight away.
 * fixed_device names an ALSA device to use instead of choosing an output and routing to it; tests
 * pass "null". Normally NULL. Returns NULL if it can't start. */
tr_player *tr_player_new(const char *dir, const char *fixed_device);

void tr_player_free(tr_player *p);

/* Ask for something. Returns straight away, except TR_CMD_RELEASE, which returns once the audio
 * device is free (or after a second, if something is badly wrong). */
void tr_player_command(tr_player *p, tr_music_cmd cmd);

void tr_player_status(tr_player *p, tr_music_status *out);

/* Whether it's playing, and so holding the audio device. */
int tr_player_is_playing(tr_player *p);

/* Update out if the track list has changed since it was last copied. */
void tr_player_library(tr_player *p, tr_music_library *out);

#endif
