#include "url.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int starts_with_nocase(const char *s, const char *prefix)
{
	return !strncasecmp(s, prefix, strlen(prefix));
}

int url_parse(const char *url, url_parts *out)
{
	memset(out, 0, sizeof(*out));
	const char *p;
	if (starts_with_nocase(url, "https://")) {
		out->secure = 1;
		out->port = 443;
		p = url + 8;
	} else if (starts_with_nocase(url, "http://")) {
		out->port = 80;
		p = url + 7;
	} else {
		return 0;
	}
	const size_t auth = strcspn(p, "/?#");
	if (!auth || memchr(p, '@', auth))     /* user:pass@ is how links lie about where they go */
		return 0;
	const char *colon = NULL;
	if (p[0] == '[') {                     /* [v6]:port */
		const char *close = memchr(p, ']', auth);
		if (!close)
			return 0;
		const size_t host_n = (size_t)(close - p) - 1;
		if (host_n >= sizeof(out->host))
			return 0;
		memcpy(out->host, p + 1, host_n);
		if ((size_t)(close + 1 - p) < auth && close[1] == ':')
			colon = close + 1;
	} else {
		colon = memchr(p, ':', auth);
		const size_t host_n = colon ? (size_t)(colon - p) : auth;
		if (!host_n || host_n >= sizeof(out->host))
			return 0;
		memcpy(out->host, p, host_n);
	}
	for (char *h = out->host; *h; h++) {
		if ((unsigned char)*h <= ' ' || *h == '/' || *h == '\\')
			return 0;
		*h = (char)tolower((unsigned char)*h);
	}
	if (colon) {
		char *end;
		const long port = strtol(colon + 1, &end, 10);
		if (end != p + auth || port < 1 || port > 65535)
			return 0;
		out->port = (int)port;
	}
	const char *rest = p + auth;
	const size_t rest_n = strcspn(rest, "#");
	if (rest_n + 2 >= sizeof(out->path))
		return 0;
	size_t n = 0;
	if (rest[0] != '/')
		out->path[n++] = '/';
	memcpy(out->path + n, rest, rest_n);
	for (char *c = out->path; *c; c++)
		if ((unsigned char)*c <= ' ' || *c == 0x7f)    /* nothing here may break a request line */
			return 0;
	return 1;
}

/* Copy src, percent-encoding what can't go in a URL as it stands. */
static int add_clean(char *out, size_t cap, size_t *n, const char *src, size_t src_n)
{
	static const char HEX[] = "0123456789ABCDEF";
	for (size_t i = 0; i < src_n; i++) {
		const unsigned char c = (unsigned char)src[i];
		if (*n + 4 >= cap)
			return 0;
		if (c == '\n' || c == '\r' || c == '\t')
			continue;
		if (c <= ' ' || c >= 0x7f || c == '"' || c == '<' || c == '>') {
			out[(*n)++] = '%';
			out[(*n)++] = HEX[c >> 4];
			out[(*n)++] = HEX[c & 15];
		} else {
			out[(*n)++] = (char)c;
		}
	}
	out[*n] = '\0';
	return 1;
}

/* Take the /./ and /../ out of a path, leaving any query alone. */
static void tidy_path(char *path)
{
	char *query = strchr(path, '?');
	char saved[4096] = "";
	if (query) {
		snprintf(saved, sizeof(saved), "%s", query);
		*query = '\0';
	}
	char *out = path;
	const char *in = path;
	while (*in) {
		const char *seg = in + 1;      /* in sits on a '/' */
		const size_t len = strcspn(seg, "/");
		const int last = !seg[len];
		if (len == 1 && seg[0] == '.') {
			in = seg + len;
			if (last)
				*out++ = '/';
		} else if (len == 2 && seg[0] == '.' && seg[1] == '.') {
			while (out > path && *--out != '/')
				;
			in = seg + len;
			if (last)
				*out++ = '/';
		} else {
			memmove(out, in, len + 1);
			out += len + 1;
			in = seg + len;
		}
	}
	if (out == path)
		*out++ = '/';
	*out = '\0';
	if (query)
		strcat(path, saved);
}

int url_resolve(const char *base, const char *ref, char *out, size_t cap)
{
	while (*ref == ' ' || *ref == '\n' || *ref == '\t' || *ref == '\r')
		ref++;
	size_t ref_n = strlen(ref);
	while (ref_n && (ref[ref_n - 1] == ' ' || ref[ref_n - 1] == '\n' || ref[ref_n - 1] == '\t' || ref[ref_n - 1] == '\r'))
		ref_n--;
	size_t n = 0;
	url_parts parts;
	if (cap)
		out[0] = '\0';
	const size_t scheme = strcspn(ref, ":/?#");
	if (scheme < ref_n && ref[scheme] == ':') {
		if (!starts_with_nocase(ref, "http://") && !starts_with_nocase(ref, "https://"))
			return 0;          /* javascript:, mailto:, data:, file: and the rest aren't for us */
		if (!add_clean(out, cap, &n, ref, ref_n))
			return 0;
		return url_parse(out, &parts);
	}
	url_parts b;
	if (!url_parse(base, &b))
		return 0;
	char origin[300];
	const int v6 = strchr(b.host, ':') != NULL;
	const int default_port = b.port == (b.secure ? 443 : 80);
	if (default_port)
		snprintf(origin, sizeof(origin), "%s://%s%s%s", b.secure ? "https" : "http", v6 ? "[" : "", b.host, v6 ? "]" : "");
	else
		snprintf(origin, sizeof(origin), "%s://%s%s%s:%d", b.secure ? "https" : "http", v6 ? "[" : "", b.host, v6 ? "]" : "", b.port);

	if (ref_n >= 2 && ref[0] == '/' && ref[1] == '/') {
		if (!add_clean(out, cap, &n, b.secure ? "https:" : "http:", b.secure ? 6 : 5) || !add_clean(out, cap, &n, ref, ref_n))
			return 0;
		return url_parse(out, &parts);
	}
	char path[4096 + 1];
	size_t p = 0;
	path[0] = '\0';
	if (!ref_n || ref[0] == '#') {
		add_clean(path, sizeof(path), &p, b.path, strlen(b.path));
	} else if (ref[0] == '?') {
		add_clean(path, sizeof(path), &p, b.path, strcspn(b.path, "?"));
		if (!add_clean(path, sizeof(path), &p, ref, ref_n))
			return 0;
	} else if (ref[0] == '/') {
		if (!add_clean(path, sizeof(path), &p, ref, ref_n))
			return 0;
	} else {
		const size_t path_only = strcspn(b.path, "?");
		size_t dir = path_only;
		while (dir && b.path[dir - 1] != '/')
			dir--;
		add_clean(path, sizeof(path), &p, b.path, dir);
		if (!add_clean(path, sizeof(path), &p, ref, ref_n))
			return 0;
	}
	path[strcspn(path, "#")] = '\0';
	tidy_path(path);
	if (strlen(origin) + strlen(path) + 1 > cap)
		return 0;
	snprintf(out, cap, "%s%s", origin, path);
	return url_parse(out, &parts);
}

int url_from_typed(const char *typed, char *out, size_t cap)
{
	char with_scheme[8192];
	if (strstr(typed, "://"))
		snprintf(with_scheme, sizeof(with_scheme), "%s", typed);
	else
		snprintf(with_scheme, sizeof(with_scheme), "https://%s", typed);
	return url_resolve("https://localhost/", with_scheme, out, cap);
}

size_t url_encode(const char *s, int form, char *out, size_t cap)
{
	static const char HEX[] = "0123456789ABCDEF";
	size_t n = 0;
	for (; *s; s++) {
		const unsigned char c = (unsigned char)*s;
		if (n + 4 >= cap)
			return 0;
		if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
			out[n++] = (char)c;
		} else if (c == ' ' && form) {
			out[n++] = '+';
		} else {
			out[n++] = '%';
			out[n++] = HEX[c >> 4];
			out[n++] = HEX[c & 15];
		}
	}
	if (cap)
		out[n] = '\0';
	return n;
}

void url_host(const char *url, char *out, size_t cap)
{
	url_parts p;
	snprintf(out, cap, "%s", url_parse(url, &p) ? p.host : url);
}
