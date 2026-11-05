/* Just enough JSON for the Gemini API: find a value by path in text we don't trust, and write strings. */
#ifndef WEBD_JSON_H
#define WEBD_JSON_H

#include <stddef.h>

#include "doc.h"

/* A value inside some JSON, as it stands in the text. */
typedef struct {
	const char *s;
	size_t n;
} json_val;

/* Look up "a.b.c" through nested objects. 0 if it's not there or the JSON is bad on the way. */
int json_get(const char *js, size_t n, const char *path, json_val *out);

/* Walk an array: start with *at = 0, and each call gives the next item. 0 when there are no more, or it isn't an array. */
int json_each(json_val array, size_t *at, json_val *item);

/* A JSON string's value, unescaped to UTF-8 and appended to out. 0 if v isn't a good string. */
int json_string(json_val v, sb *out);

/* Is this one whole, well-formed JSON value? */
int json_valid(const char *js, size_t n);

/* Append s as a quoted JSON string. Bytes that aren't valid UTF-8 become U+FFFD: the API refuses them. */
void json_quote(sb *out, const char *s, size_t n);

long json_number(json_val v);

#endif
