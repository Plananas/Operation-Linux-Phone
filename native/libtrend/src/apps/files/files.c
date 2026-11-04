/* Files app behaviour: following what the server says, and the one key. */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "files_state.h"
#include "trend/apps/music.h"          /* tr_music_latin1: filenames are UTF-8, the font is Latin-1 */

size_t tr_files_size(void)
{
	return sizeof(tr_files);
}

size_t tr_files_status_size(void)
{
	return sizeof(tr_files_status);
}

void tr_files_init(tr_files *out)
{
	memset(out, 0, sizeof(*out));
}

void tr_files_status_init(tr_files_status *out)
{
	memset(out, 0, sizeof(*out));
	out->shown.free_bytes = -1;
}

int tr_files_phase(const tr_files_status *st)
{
	return st->shown.phase;
}

const char *tr_files_pin(const tr_files_status *st)
{
	return st->shown.pin;
}

/* ---- the server's output ---- */

static void apply_transfer(files_shown *shown, const char *text)
{
	int slot, consumed = 0;
	char dir, state;
	long long done, total;
	if (sscanf(text, "%d %c %c %lld %lld %n", &slot, &dir, &state, &done, &total, &consumed) != 5 || !consumed ||
	    slot < 0 || slot >= FILES_SLOTS)
		return;
	files_xfer *x = &shown->xfers[slot];
	memset(x, 0, sizeof(*x));
	x->used = 1;
	x->sending = dir == 'd';
	x->active = state == 'a';
	x->failed = state == 'x';
	x->done = done;
	x->total = total;
	tr_music_latin1(text + consumed, x->name, sizeof(x->name));
}

static void apply_line(files_shown *shown, const char *line)
{
	if (line[0] == '\0' || line[1] != ' ')
		return;
	const char *text = line + 2;
	switch (line[0]) {
	case 'U': {
		char pin[8];
		int port;
		if (sscanf(text, "%7s %d", pin, &port) == 2) {
			memcpy(shown->pin, pin, sizeof(pin));
			shown->port = port;
			shown->phase = TR_FILES_ON;
		}
		break;
	}
	case 'A':
		snprintf(shown->address, sizeof(shown->address), "%s", text);
		break;
	case 'F':
		shown->free_bytes = strtoll(text, NULL, 10);
		break;
	case 'T':
		apply_transfer(shown, text);
		break;
	case 'X':
		snprintf(shown->reason, sizeof(shown->reason), "%s", text);
		break;
	default:
		break;
	}
}

void tr_files_feed(tr_files_status *st, const char *data, size_t n)
{
	const files_shown before = st->shown;
	for (size_t i = 0; i < n; i++) {
		if (data[i] != '\n') {
			if (st->line_len + 1 < sizeof(st->line))
				st->line[st->line_len++] = data[i];
			else
				st->line_too_long = 1;
			continue;
		}
		st->line[st->line_len] = '\0';
		if (!st->line_too_long)
			apply_line(&st->shown, st->line);
		st->line_len = 0;
		st->line_too_long = 0;
	}
	if (memcmp(&before, &st->shown, sizeof(before)))
		st->version++;
}

void tr_files_set_phase(tr_files_status *st, int phase, const char *message)
{
	if (phase == TR_FILES_STARTING) {
		const unsigned version = st->version;
		tr_files_status_init(st);
		st->version = version;
	} else if (phase == TR_FILES_OFF) {
		st->shown.pin[0] = '\0';
		st->shown.address[0] = '\0';
		for (int i = 0; i < FILES_SLOTS; i++)
			st->shown.xfers[i].active = 0;
	}
	st->shown.phase = phase;
	if (message)
		snprintf(st->shown.reason, sizeof(st->shown.reason), "%s", message);
	st->version++;
}

/* ---- the key ---- */

static int on_key(int x, int y)
{
	return x >= KEY_X0 && x < KEY_X1 && y >= KEY_Y0 && y < KEY_Y1;
}

int tr_files_touch(const tr_files *in, tr_files *out, const tr_files_status *st, int event, int x, int y)
{
	const int was_pressed = in->pressed;
	const int inside = on_key(x, y);
	out->pressed = event == TR_FILES_DOWN ? inside : event == TR_FILES_MOVE ? was_pressed && inside : 0;
	if (event != TR_FILES_UP || !was_pressed || !inside)
		return TR_FILES_NONE;
	switch (st->shown.phase) {
	case TR_FILES_OFF: return TR_FILES_START;
	case TR_FILES_ON: return TR_FILES_STOP;
	default: return TR_FILES_NONE;
	}
}

static int any_active(const files_shown *shown)
{
	for (int i = 0; i < FILES_SLOTS; i++)
		if (shown->xfers[i].active)
			return 1;
	return 0;
}

uint64_t tr_files_frame_key(const tr_files *s, const tr_files_status *st, double now)
{
	const uint64_t tick = any_active(&st->shown) ? (uint64_t)(now * 15.0) : 0;
	return tick << 33 | (uint64_t)st->version << 1 | (uint64_t)(s->pressed != 0);
}

void tr_files_format_size(int64_t bytes, char *out, size_t cap)
{
	static const char *const UNITS[] = { "KB", "MB", "GB", "TB" };
	if (bytes < 1024) {
		snprintf(out, cap, "%" PRId64 " B", bytes < 0 ? 0 : bytes);
		return;
	}
	double v = (double)bytes / 1024.0;
	int unit = 0;
	while (v >= 1024.0 && unit < 3) {
		v /= 1024.0;
		unit++;
	}
	snprintf(out, cap, "%.1f %s", v, UNITS[unit]);
}
