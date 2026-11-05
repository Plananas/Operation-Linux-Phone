/* Music text conversion. Also compiled into libtrendplay (native/player/), so the two libraries
 * stay independent of each other. */
#include <string.h>

#include "trend/apps/music.h"

/* The code point at s, and how many bytes it took. Bytes that aren't valid UTF-8 are read as
 * Latin-1, which is what old tags and filenames usually are. */
static unsigned decode_utf8(const unsigned char *s, int *used)
{
	const unsigned lead = s[0];
	const int extra = lead >= 0xF0 && lead < 0xF8 ? 3 : lead >= 0xE0 ? (lead < 0xF0 ? 2 : 0) : lead >= 0xC2 ? 1 : 0;
	unsigned cp = extra == 3 ? lead & 0x07u : extra == 2 ? lead & 0x0Fu : extra == 1 ? lead & 0x1Fu : lead;
	for (int i = 1; i <= extra; i++) {
		if ((s[i] & 0xC0u) != 0x80u) {
			*used = 1;
			return lead;
		}
		cp = cp << 6 | (s[i] & 0x3Fu);
	}
	*used = extra + 1;
	return cp;
}

static char to_latin1(unsigned cp)
{
	switch (cp) {
	case 0x2018: case 0x2019: return '\'';
	case 0x201C: case 0x201D: return '"';
	case 0x2013: case 0x2014: return '-';
	default: break;
	}
	return cp < 0x20 || (cp >= 0x7F && cp < 0xA0) || cp > 0xFF ? '?' : (char)cp;
}

void tr_music_latin1(const char *utf8, char *out, size_t cap)
{
	const unsigned char *s = (const unsigned char *)utf8;
	size_t n = 0;
	while (*s && n + 1 < cap) {
		int used;
		const unsigned cp = decode_utf8(s, &used);
		out[n++] = to_latin1(cp);
		s += used;
	}
	out[n] = '\0';
}

static void spaces_for_underscores(char *s)
{
	for (; *s; s++)
		if (*s == '_')
			*s = ' ';
}

void tr_music_display_name(const char *path, char *out, size_t cap)
{
	const char *slash = strrchr(path, '/');
	tr_music_latin1(slash ? slash + 1 : path, out, cap);
	char *dot = strrchr(out, '.');
	if (dot && dot != out)
		*dot = '\0';
	spaces_for_underscores(out);
}

void tr_music_folder_name(const char *folder, char *out, size_t cap)
{
	tr_music_latin1(folder, out, cap);
	spaces_for_underscores(out);
}
