/* The parts of filesd that only look at bytes: parsing requests and checking names. No I/O and no
 * state, so all of it can be tested alone. Everything here treats its input as hostile. */
#ifndef FILESD_HTTP_H
#define FILESD_HTTP_H

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

typedef struct {
	const char *method, *target;   /* target has its query string removed */
	const char *cookie, *range, *expect;   /* NULL if absent */
	int64_t content_length;        /* -1 if absent */
	int same_origin_marker;        /* the X-Trend header: cross-site pages can't send it */
} http_req;

/* Where the head ends (the offset just after the blank line), or -1 if it hasn't arrived yet. */
ssize_t http_head_end(const char *buf, size_t n);

/* Parse a NUL-terminated request head in place. 0 if it's well formed, -1 if not. Chunked bodies are
 * refused here, so a body's length is always known. */
int http_parse_head(char *head, http_req *out);

/* Percent-decode raw[0..n) into out. Returns the length, or -1 for bad hex, a NUL byte or no room. */
int http_decode(const char *raw, size_t n, char *out, size_t cap);

/* Is this safe as one file or folder name? Rules out "", ".", "..", every hidden name, slashes,
 * backslashes, control characters, bad UTF-8 and anything over 255 bytes. */
int fs_name_ok(const char *name);

/* A Range header against a file of the given size: *from .. *to inclusive. 1 if it applies, 0 to send
 * the whole file, -1 if it can't be satisfied. */
int http_parse_range(const char *value, int64_t size, int64_t *from, int64_t *to);

/* The value of one cookie, or -1 if it isn't there or won't fit. */
int http_cookie_value(const char *header, const char *name, char *out, size_t cap);

/* s as the inside of a JSON string, or -1 if it won't fit. */
int json_escape(const char *s, char *out, size_t cap);

/* s percent-encoded for filename*=UTF-8'', or -1 if it won't fit. */
int http_encode_attr(const char *s, char *out, size_t cap);

#endif
