#define _GNU_SOURCE
#include "http.h"

#include <stdio.h>
#include <string.h>
#include <strings.h>

ssize_t http_head_end(const char *buf, size_t n)
{
	const char *end = memmem(buf, n, "\r\n\r\n", 4);
	return end ? (ssize_t)(end - buf) + 4 : -1;
}

/* Digits only, from s up to end, with overflow refused. */
static int parse_i64(const char *s, const char *end, int64_t *out)
{
	int64_t v = 0;
	if (s == end)
		return -1;
	for (; s < end; s++) {
		if (*s < '0' || *s > '9')
			return -1;
		const int d = *s - '0';
		if (v > (INT64_MAX - d) / 10)
			return -1;
		v = v * 10 + d;
	}
	*out = v;
	return 0;
}

/* No spaces or control characters anywhere in s. */
static int is_token(const char *s)
{
	for (; *s; s++)
		if ((unsigned char)*s < 0x21 || *s == 0x7f)
			return 0;
	return 1;
}

static int apply_header(http_req *out, const char *name, const char *value)
{
	if (!strcasecmp(name, "content-length")) {
		int64_t v;
		if (out->content_length >= 0 || parse_i64(value, value + strlen(value), &v))
			return -1;
		out->content_length = v;
	} else if (!strcasecmp(name, "transfer-encoding")) {
		return -1;
	} else if (!strcasecmp(name, "cookie")) {
		out->cookie = value;
	} else if (!strcasecmp(name, "range")) {
		out->range = value;
	} else if (!strcasecmp(name, "expect")) {
		out->expect = value;
	} else if (!strcasecmp(name, "x-trend")) {
		out->same_origin_marker = 1;
	}
	return 0;
}

int http_parse_head(char *head, http_req *out)
{
	memset(out, 0, sizeof(*out));
	out->content_length = -1;

	char *line_end = strstr(head, "\r\n");
	if (!line_end)
		return -1;
	*line_end = '\0';
	char *target = strchr(head, ' ');
	if (!target)
		return -1;
	*target++ = '\0';
	char *version = strchr(target, ' ');
	if (!version)
		return -1;
	*version++ = '\0';
	if (strcmp(version, "HTTP/1.1") && strcmp(version, "HTTP/1.0"))
		return -1;
	if (!is_token(head) || !is_token(target) || target[0] != '/')
		return -1;
	char *query = strchr(target, '?');
	if (query)
		*query = '\0';
	out->method = head;
	out->target = target;

	char *line = line_end + 2;
	while (*line && !(line[0] == '\r' && line[1] == '\n')) {
		line_end = strstr(line, "\r\n");
		if (!line_end)
			return -1;
		*line_end = '\0';
		if (*line == ' ' || *line == '\t')     /* folded headers can smuggle values */
			return -1;
		char *colon = strchr(line, ':');
		if (!colon || colon == line)
			return -1;
		*colon = '\0';
		char *value = colon + 1;
		while (*value == ' ' || *value == '\t')
			value++;
		char *tail = value + strlen(value);
		while (tail > value && (tail[-1] == ' ' || tail[-1] == '\t'))
			*--tail = '\0';
		if (apply_header(out, line, value))
			return -1;
		line = line_end + 2;
	}
	return 0;
}

static int hex_value(char c)
{
	if (c >= '0' && c <= '9')
		return c - '0';
	if (c >= 'a' && c <= 'f')
		return c - 'a' + 10;
	if (c >= 'A' && c <= 'F')
		return c - 'A' + 10;
	return -1;
}

int http_decode(const char *raw, size_t n, char *out, size_t cap)
{
	size_t len = 0;
	for (size_t i = 0; i < n; i++) {
		int c = (unsigned char)raw[i];
		if (c == '%') {
			if (n - i < 3)
				return -1;
			const int hi = hex_value(raw[i + 1]), lo = hex_value(raw[i + 2]);
			if (hi < 0 || lo < 0)
				return -1;
			c = hi * 16 + lo;
			i += 2;
		}
		if (c == 0 || len + 1 >= cap)
			return -1;
		out[len++] = (char)c;
	}
	out[len] = '\0';
	return (int)len;
}

/* The length of the valid UTF-8 sequence at s, or 0. Refuses overlong forms and surrogates. */
static int utf8_len(const unsigned char *s)
{
	const unsigned c = s[0];
	if (c < 0x80)
		return 1;
	if (c >= 0xC2 && c <= 0xDF)
		return (s[1] & 0xC0) == 0x80 ? 2 : 0;
	if (c >= 0xE0 && c <= 0xEF) {
		const unsigned lo = c == 0xE0 ? 0xA0 : 0x80, hi = c == 0xED ? 0x9F : 0xBF;
		return s[1] >= lo && s[1] <= hi && (s[2] & 0xC0) == 0x80 ? 3 : 0;
	}
	if (c >= 0xF0 && c <= 0xF4) {
		const unsigned lo = c == 0xF0 ? 0x90 : 0x80, hi = c == 0xF4 ? 0x8F : 0xBF;
		return s[1] >= lo && s[1] <= hi && (s[2] & 0xC0) == 0x80 && (s[3] & 0xC0) == 0x80 ? 4 : 0;
	}
	return 0;
}

int fs_name_ok(const char *name)
{
	const size_t n = strlen(name);
	if (n == 0 || n > 255 || name[0] == '.')
		return 0;
	for (const unsigned char *s = (const unsigned char *)name; *s;) {
		if (*s < 0x20 || *s == 0x7f || *s == '/' || *s == '\\')
			return 0;
		const int len = utf8_len(s);
		if (!len)
			return 0;
		s += len;
	}
	return 1;
}

int http_parse_range(const char *value, int64_t size, int64_t *from, int64_t *to)
{
	if (strncmp(value, "bytes=", 6))
		return 0;
	const char *a = value + 6, *dash = strchr(a, '-');
	if (!dash || strchr(a, ','))           /* several ranges: just send the file */
		return 0;
	const char *end = dash + strlen(dash);
	int64_t lo, hi;
	if (a == dash) {                       /* bytes=-n: the last n bytes */
		if (parse_i64(dash + 1, end, &lo))
			return 0;
		if (lo == 0 || size == 0)
			return -1;
		*from = lo >= size ? 0 : size - lo;
		*to = size - 1;
		return 1;
	}
	if (parse_i64(a, dash, &lo))
		return 0;
	if (dash + 1 == end)
		hi = size - 1;
	else if (parse_i64(dash + 1, end, &hi))
		return 0;
	if (lo >= size || hi < lo)
		return -1;
	*from = lo;
	*to = hi >= size ? size - 1 : hi;
	return 1;
}

int http_cookie_value(const char *header, const char *name, char *out, size_t cap)
{
	const size_t name_len = strlen(name);
	const char *p = header;
	while (*p) {
		while (*p == ' ' || *p == ';')
			p++;
		const char *end = strchr(p, ';');
		const size_t len = end ? (size_t)(end - p) : strlen(p);
		if (len > name_len && !strncmp(p, name, name_len) && p[name_len] == '=') {
			const size_t v = len - name_len - 1;
			if (v + 1 > cap)
				return -1;
			memcpy(out, p + name_len + 1, v);
			out[v] = '\0';
			return 0;
		}
		p += len;
	}
	return -1;
}

int json_escape(const char *s, char *out, size_t cap)
{
	size_t n = 0;
	for (; *s; s++) {
		const unsigned char c = (unsigned char)*s;
		const int plain = c >= 0x20 && c != '"' && c != '\\';
		const size_t need = plain ? 1 : c == '"' || c == '\\' ? 2 : 6;
		if (n + need + 1 > cap)
			return -1;
		if (plain) {
			out[n++] = (char)c;
		} else if (need == 2) {
			out[n++] = '\\';
			out[n++] = (char)c;
		} else {
			n += (size_t)snprintf(out + n, 7, "\\u%04x", c);
		}
	}
	out[n] = '\0';
	return (int)n;
}

int http_encode_attr(const char *s, char *out, size_t cap)
{
	size_t n = 0;
	for (; *s; s++) {
		const unsigned char c = (unsigned char)*s;
		const int plain = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
				  c == '-' || c == '.' || c == '_' || c == '~';
		if (n + (plain ? 1 : 3) + 1 > cap)
			return -1;
		if (plain)
			out[n++] = (char)c;
		else
			n += (size_t)snprintf(out + n, 4, "%%%02X", c);
	}
	out[n] = '\0';
	return (int)n;
}
