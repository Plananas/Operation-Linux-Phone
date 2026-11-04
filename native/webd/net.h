/* One HTTP or HTTPS request. Certificates are always checked. A request can be interrupted: while it waits,
 * net_request.watch_fd is watched too, and cancel decides whether whatever arrived there stops it. */
#ifndef WEBD_NET_H
#define WEBD_NET_H

#include <stddef.h>

#include "doc.h"

enum { NET_OK, NET_FAILED, NET_CANCELLED };

typedef struct {
	const char *url;
	const char *method;            /* NULL: GET */
	const char *headers;           /* extra lines, each ending \r\n */
	const char *body;
	size_t body_n;
	int allow_private;             /* may it reach this phone or the home network? */
	int gzip;                      /* say we take gzip */
	int timeout_s;                 /* for connecting, and for any silence after that */
	size_t max_body;
	int watch_fd;                  /* -1: none */
	int (*cancel)(void *ctx);      /* something came in on watch_fd: stop? */
	void (*on_data)(void *ctx, const char *data, size_t n, int status);    /* set: stream the body here */
	void (*on_progress)(void *ctx, size_t received);
	void *ctx;
} net_request;

typedef struct {
	int status;
	sb body;
	char content_type[128];
	char location[4096];
	int gzipped;
	char error[160];
} net_response;

int net_fetch(const net_request *req, net_response *resp);
void net_response_free(net_response *resp);

#endif
