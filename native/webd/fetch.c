#include "fetch.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ascii.h"
#include "url.h"

#define STBI_ONLY_JPEG
#define STBI_ONLY_PNG
#define STBI_ONLY_GIF
#define STBI_NO_STDIO
#define STBI_NO_LINEAR
#define STBI_NO_HDR
#define STBI_MAX_DIMENSIONS 8192
#define STB_IMAGE_IMPLEMENTATION
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wall"
#pragma GCC diagnostic ignored "-Wextra"
#pragma GCC diagnostic ignored "-Wconversion"
#pragma GCC diagnostic ignored "-Wshadow"
#include <stb_image.h>
#pragma GCC diagnostic pop

enum { REDIRECTS_MAX = 8, GZIP_MIN_HEADER = 10 };

/* Past gzip's own header, to the deflate data. 0 if it isn't gzip. */
static size_t gzip_header(const unsigned char *s, size_t n)
{
	if (n < GZIP_MIN_HEADER + 8 || s[0] != 0x1f || s[1] != 0x8b || s[2] != 8)
		return 0;
	const unsigned flags = s[3];
	size_t i = GZIP_MIN_HEADER;
	if (flags & 4) {
		if (i + 2 > n)
			return 0;
		i += 2u + (size_t)(s[i] | s[i + 1] << 8);
	}
	for (unsigned bit = 8; bit <= 16; bit <<= 1)
		if (flags & bit) {
			while (i < n && s[i])
				i++;
			i++;
		}
	if (flags & 2)
		i += 2;
	return i < n ? i : 0;
}

static void gunzip(net_response *resp)
{
	const size_t at = gzip_header((const unsigned char *)resp->body.s, resp->body.n);
	if (!at) {
		snprintf(resp->error, sizeof(resp->error), "the server's answer was garbled");
		return;
	}
	int out_n = 0;
	char *out = stbi_zlib_decode_noheader_malloc(resp->body.s + at, (int)(resp->body.n - at), &out_n);
	if (!out || out_n < 0) {
		free(out);
		snprintf(resp->error, sizeof(resp->error), "the server's answer was garbled");
		return;
	}
	sb_free(&resp->body);
	sb_add(&resp->body, out, (size_t)out_n);
	free(out);
	resp->gzipped = 0;
}

int fetch_follow(net_request req, net_response *resp, char *final)
{
	char url[4096];
	snprintf(url, sizeof(url), "%s", req.url);
	snprintf(final, 4096, "%s", url);
	for (int hops = 0; hops <= REDIRECTS_MAX; hops++) {
		req.url = url;
		snprintf(final, 4096, "%s", url);
		const int r = net_fetch(&req, resp);
		if (r != NET_OK)
			return r;
		const int redirect = resp->status >= 300 && resp->status < 400 && resp->location[0];
		if (!redirect) {
			if (resp->gzipped) {
				gunzip(resp);
				if (resp->error[0])
					return NET_FAILED;
			}
			return NET_OK;
		}
		char next[4096];
		if (!url_resolve(url, resp->location, next, sizeof(next))) {
			snprintf(resp->error, sizeof(resp->error), "the page redirects somewhere this can't go");
			return NET_FAILED;
		}
		memcpy(url, next, sizeof(url));
		if (resp->status != 307 && resp->status != 308) {
			req.method = NULL;
			req.body = NULL;
			req.body_n = 0;
			req.headers = NULL;
		}
		net_response_free(resp);
	}
	memset(resp, 0, sizeof(*resp));
	snprintf(resp->error, sizeof(resp->error), "too many redirects");
	return NET_FAILED;
}

int fetch_decode_art(const char *data, size_t n, int rows, uint8_t *out)
{
	int w, h, channels;
	unsigned char *px = stbi_load_from_memory((const unsigned char *)data, (int)n, &w, &h, &channels, 3);
	if (!px)
		return 0;
	ascii_image(px, w, h, WEB_ART_COLS, rows, out);
	stbi_image_free(px);
	return 1;
}
