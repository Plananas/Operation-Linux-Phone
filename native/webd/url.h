/* URLs: pure string work. */
#ifndef WEBD_URL_H
#define WEBD_URL_H

#include <stddef.h>

typedef struct {
	int secure;
	char host[256];
	int port;
	char path[4096];               /* with its query, and no fragment */
} url_parts;

/* 0 unless it's a good http or https URL. */
int url_parse(const char *url, url_parts *out);

/* ref read against base, as a whole URL, tidied up and made safe to send. 0 if there's no sense in it. */
int url_resolve(const char *base, const char *ref, char *out, size_t cap);

/* What someone typed into the address bar, as a URL. */
int url_from_typed(const char *typed, char *out, size_t cap);

/* s with everything but the safe characters as %XX; spaces as + when form is set. Returns the length, or 0 if
 * cap is too small. */
size_t url_encode(const char *s, int form, char *out, size_t cap);

/* The host alone, for showing someone. */
void url_host(const char *url, char *out, size_t cap);

#endif
