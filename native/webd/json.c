#include "json.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { DEPTH_MAX = 64 };

static size_t skip_ws(const char *s, size_t n, size_t i)
{
	while (i < n && (s[i] == ' ' || s[i] == '\n' || s[i] == '\r' || s[i] == '\t'))
		i++;
	return i;
}

/* The index just past the value at i, or 0 if it's malformed. */
static size_t skip_value(const char *s, size_t n, size_t i, int depth);

static size_t skip_string(const char *s, size_t n, size_t i)
{
	if (i >= n || s[i] != '"')
		return 0;
	for (i++; i < n; i++) {
		const unsigned char c = (unsigned char)s[i];
		if (c == '"')
			return i + 1;
		if (c < 0x20)
			return 0;
		if (c == '\\') {
			i++;
			if (i >= n)
				return 0;
		}
	}
	return 0;
}

static size_t skip_container(const char *s, size_t n, size_t i, int depth, char close, int keyed)
{
	if (depth >= DEPTH_MAX)
		return 0;
	i = skip_ws(s, n, i + 1);
	if (i < n && s[i] == close)
		return i + 1;
	for (;;) {
		if (keyed) {
			i = skip_string(s, n, skip_ws(s, n, i));
			if (!i)
				return 0;
			i = skip_ws(s, n, i);
			if (i >= n || s[i] != ':')
				return 0;
			i++;
		}
		i = skip_value(s, n, skip_ws(s, n, i), depth + 1);
		if (!i)
			return 0;
		i = skip_ws(s, n, i);
		if (i >= n)
			return 0;
		if (s[i] == close)
			return i + 1;
		if (s[i] != ',')
			return 0;
		i++;
	}
}

static size_t skip_value(const char *s, size_t n, size_t i, int depth)
{
	if (i >= n)
		return 0;
	switch (s[i]) {
	case '"': return skip_string(s, n, i);
	case '{': return skip_container(s, n, i, depth, '}', 1);
	case '[': return skip_container(s, n, i, depth, ']', 0);
	case 't': return n - i >= 4 && !memcmp(s + i, "true", 4) ? i + 4 : 0;
	case 'f': return n - i >= 5 && !memcmp(s + i, "false", 5) ? i + 5 : 0;
	case 'n': return n - i >= 4 && !memcmp(s + i, "null", 4) ? i + 4 : 0;
	default: break;
	}
	const size_t start = i;
	while (i < n && (s[i] == '-' || s[i] == '+' || s[i] == '.' || s[i] == 'e' || s[i] == 'E' || (s[i] >= '0' && s[i] <= '9')))
		i++;
	return i > start ? i : 0;
}

int json_valid(const char *js, size_t n)
{
	const size_t end = skip_value(js, n, skip_ws(js, n, 0), 0);
	return end && skip_ws(js, n, end) == n;
}

/* Find key in the object at i. */
static int object_get(const char *s, size_t n, size_t i, const char *key, size_t key_n, json_val *out)
{
	if (i >= n || s[i] != '{')
		return 0;
	i = skip_ws(s, n, i + 1);
	if (i < n && s[i] == '}')
		return 0;
	while (i < n) {
		const size_t key_start = i + 1;
		const size_t after_key = skip_string(s, n, i);
		if (!after_key)
			return 0;
		const size_t this_n = after_key - 1 - key_start;
		i = skip_ws(s, n, after_key);
		if (i >= n || s[i] != ':')
			return 0;
		i = skip_ws(s, n, i + 1);
		const size_t end = skip_value(s, n, i, 0);
		if (!end)
			return 0;
		if (this_n == key_n && !memcmp(s + key_start, key, key_n)) {
			*out = (json_val){ s + i, end - i };
			return 1;
		}
		i = skip_ws(s, n, end);
		if (i >= n || s[i] != ',')
			return 0;
		i = skip_ws(s, n, i + 1);
	}
	return 0;
}

int json_get(const char *js, size_t n, const char *path, json_val *out)
{
	json_val cur = { js, n };
	while (*path) {
		const size_t key_n = strcspn(path, ".");
		json_val next;
		if (!object_get(cur.s, cur.n, skip_ws(cur.s, cur.n, 0), path, key_n, &next))
			return 0;
		cur = next;
		path += key_n + (path[key_n] == '.');
	}
	*out = cur;
	return 1;
}

static int hex4(const char *s, unsigned *out)
{
	unsigned v = 0;
	for (int i = 0; i < 4; i++) {
		const char c = s[i];
		v <<= 4;
		if (c >= '0' && c <= '9')
			v |= (unsigned)(c - '0');
		else if (c >= 'a' && c <= 'f')
			v |= (unsigned)(c - 'a' + 10);
		else if (c >= 'A' && c <= 'F')
			v |= (unsigned)(c - 'A' + 10);
		else
			return 0;
	}
	*out = v;
	return 1;
}

static void add_utf8(sb *out, unsigned cp)
{
	char u[4];
	size_t n;
	if (cp < 0x80) {
		u[0] = (char)cp;
		n = 1;
	} else if (cp < 0x800) {
		u[0] = (char)(0xc0 | cp >> 6);
		u[1] = (char)(0x80 | (cp & 0x3f));
		n = 2;
	} else if (cp < 0x10000) {
		u[0] = (char)(0xe0 | cp >> 12);
		u[1] = (char)(0x80 | (cp >> 6 & 0x3f));
		u[2] = (char)(0x80 | (cp & 0x3f));
		n = 3;
	} else {
		u[0] = (char)(0xf0 | cp >> 18);
		u[1] = (char)(0x80 | (cp >> 12 & 0x3f));
		u[2] = (char)(0x80 | (cp >> 6 & 0x3f));
		u[3] = (char)(0x80 | (cp & 0x3f));
		n = 4;
	}
	sb_add(out, u, n);
}

int json_string(json_val v, sb *out)
{
	if (v.n < 2 || v.s[0] != '"' || v.s[v.n - 1] != '"')
		return 0;
	const char *s = v.s + 1;
	const size_t n = v.n - 2;
	for (size_t i = 0; i < n; i++) {
		if (s[i] != '\\') {
			sb_add(out, s + i, 1);
			continue;
		}
		if (++i >= n)
			return 0;
		char c = s[i];
		switch (c) {
		case 'n': c = '\n'; break;
		case 't': c = '\t'; break;
		case 'r': c = '\r'; break;
		case 'b': c = '\b'; break;
		case 'f': c = '\f'; break;
		case 'u': {
			unsigned cp;
			if (i + 4 >= n || !hex4(s + i + 1, &cp))
				return 0;
			i += 4;
			if (cp >= 0xd800 && cp < 0xdc00 && i + 6 < n && s[i + 1] == '\\' && s[i + 2] == 'u') {
				unsigned low;
				if (hex4(s + i + 3, &low) && low >= 0xdc00 && low < 0xe000) {
					cp = 0x10000 + ((cp - 0xd800) << 10) + (low - 0xdc00);
					i += 6;
				}
			}
			if (cp >= 0xd800 && cp < 0xe000)
				cp = 0xfffd;
			add_utf8(out, cp);
			continue;
		}
		default: break;
		}
		sb_add(out, &c, 1);
	}
	if (!out->s)
		sb_add(out, "", 0);
	return 1;
}

/* How long the valid UTF-8 character at s is, or 0. */
static size_t utf8_len(const unsigned char *s, size_t n)
{
	const unsigned c = s[0];
	size_t len;
	if (c < 0x80)
		return 1;
	if (c >= 0xc2 && c < 0xe0)
		len = 2;
	else if (c >= 0xe0 && c < 0xf0)
		len = 3;
	else if (c >= 0xf0 && c < 0xf5)
		len = 4;
	else
		return 0;
	if (len > n)
		return 0;
	for (size_t i = 1; i < len; i++)
		if ((s[i] & 0xc0u) != 0x80u)
			return 0;
	if ((c == 0xe0 && s[1] < 0xa0) || (c == 0xed && s[1] >= 0xa0) || (c == 0xf0 && s[1] < 0x90) || (c == 0xf4 && s[1] >= 0x90))
		return 0;
	return len;
}

void json_quote(sb *out, const char *s, size_t n)
{
	sb_add(out, "\"", 1);
	for (size_t i = 0; i < n;) {
		const unsigned char c = (unsigned char)s[i];
		if (c == '"' || c == '\\') {
			const char esc[2] = { '\\', (char)c };
			sb_add(out, esc, 2);
			i++;
		} else if (c == '\n') {
			sb_add(out, "\\n", 2);
			i++;
		} else if (c < 0x20) {
			char esc[8];
			snprintf(esc, sizeof(esc), "\\u%04x", c);
			sb_adds(out, esc);
			i++;
		} else {
			const size_t len = utf8_len((const unsigned char *)s + i, n - i);
			if (len) {
				sb_add(out, s + i, len);
				i += len;
			} else {
				sb_add(out, "\\ufffd", 6);
				i++;
			}
		}
	}
	sb_add(out, "\"", 1);
}

long json_number(json_val v)
{
	char num[32];
	const size_t n = v.n < sizeof(num) - 1 ? v.n : sizeof(num) - 1;
	memcpy(num, v.s, n);
	num[n] = '\0';
	return strtol(num, NULL, 10);
}
