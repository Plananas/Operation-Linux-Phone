#define _GNU_SOURCE
#include "net.h"

#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include <openssl/err.h>
#include <openssl/ssl.h>
#include <openssl/x509v3.h>

#include "url.h"

#define CA_FILE "/etc/ssl/cert.pem"

enum { HEAD_MAX = 64 * 1024, CHUNK_LINE = 32 };

typedef struct {
	const net_request *req;
	net_response *resp;
	int fd;
	SSL *ssl;
	time_t deadline;
	int result;
} conn;

static SSL_CTX *tls_context(void)
{
	static SSL_CTX *ctx;
	if (ctx)
		return ctx;
	ctx = SSL_CTX_new(TLS_client_method());
	if (!ctx)
		return NULL;
	SSL_CTX_set_min_proto_version(ctx, TLS1_2_VERSION);
	SSL_CTX_set_options(ctx, SSL_OP_IGNORE_UNEXPECTED_EOF);
	SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, NULL);
	if (SSL_CTX_load_verify_file(ctx, CA_FILE) != 1) {
		SSL_CTX_free(ctx);
		ctx = NULL;
	}
	return ctx;
}

static void fail(conn *c, const char *what)
{
	if (c->result == NET_OK) {
		c->result = NET_FAILED;
		snprintf(c->resp->error, sizeof(c->resp->error), "%s", what);
	}
}

static void touch_deadline(conn *c)
{
	c->deadline = time(NULL) + (c->req->timeout_s > 0 ? c->req->timeout_s : 30);
}

/* Wait for the socket. 1 when it's ready, 0 when it's timed out or been stopped, with the reason recorded. */
static int wait_ready(conn *c, short events)
{
	for (;;) {
		struct pollfd p[2] = { { c->fd, events, 0 }, { c->req->watch_fd, POLLIN, 0 } };
		const long left = (long)(c->deadline - time(NULL));
		if (left <= 0) {
			fail(c, "no answer: timed out");
			return 0;
		}
		const int nfds = c->req->watch_fd >= 0 ? 2 : 1;
		const int got = poll(p, (nfds_t)nfds, (int)(left > 1 ? 1000 : left * 1000));
		if (got < 0) {
			if (errno == EINTR)
				continue;
			fail(c, "couldn't wait for the network");
			return 0;
		}
		if (nfds == 2 && p[1].revents && c->req->cancel && c->req->cancel(c->req->ctx)) {
			c->result = NET_CANCELLED;
			return 0;
		}
		if (p[0].revents)
			return 1;
	}
}

static int is_private(const struct sockaddr *sa)
{
	if (sa->sa_family == AF_INET) {
		const unsigned char *a = (const unsigned char *)&((const struct sockaddr_in *)(const void *)sa)->sin_addr;
		return a[0] == 0 || a[0] == 10 || a[0] == 127 || (a[0] == 169 && a[1] == 254) || (a[0] == 172 && (a[1] & 0xf0) == 16) ||
		       (a[0] == 192 && a[1] == 168) || (a[0] == 100 && (a[1] & 0xc0) == 64);
	}
	if (sa->sa_family == AF_INET6) {
		const struct in6_addr *a6 = &((const struct sockaddr_in6 *)(const void *)sa)->sin6_addr;
		const unsigned char *a = a6->s6_addr;
		if (IN6_IS_ADDR_V4MAPPED(a6)) {
			struct sockaddr_in v4;
			memset(&v4, 0, sizeof(v4));
			v4.sin_family = AF_INET;
			memcpy(&v4.sin_addr, a + 12, 4);
			return is_private((const struct sockaddr *)&v4);
		}
		return IN6_IS_ADDR_LOOPBACK(a6) || IN6_IS_ADDR_UNSPECIFIED(a6) || (a[0] & 0xfe) == 0xfc || (a[0] == 0xfe && (a[1] & 0xc0) == 0x80);
	}
	return 1;
}

static int open_socket(conn *c, const url_parts *u)
{
	struct addrinfo hints, *found = NULL;
	char port[8];
	memset(&hints, 0, sizeof(hints));
	hints.ai_family = AF_UNSPEC;
	hints.ai_socktype = SOCK_STREAM;
	snprintf(port, sizeof(port), "%d", u->port);
	if (getaddrinfo(u->host, port, &hints, &found) || !found) {
		fail(c, "couldn't find that address: check Wi-Fi");
		return 0;
	}
	int refused_private = 0;
	for (const struct addrinfo *a = found; a; a = a->ai_next) {
		if (!c->req->allow_private && is_private(a->ai_addr)) {
			refused_private = 1;
			continue;
		}
		c->fd = socket(a->ai_family, a->ai_socktype | SOCK_CLOEXEC | SOCK_NONBLOCK, a->ai_protocol);
		if (c->fd < 0)
			continue;
		touch_deadline(c);
		if (connect(c->fd, a->ai_addr, a->ai_addrlen) == 0 || errno == EINPROGRESS) {
			int err = 0;
			socklen_t len = sizeof(err);
			if (errno != EINPROGRESS || (wait_ready(c, POLLOUT) && !getsockopt(c->fd, SOL_SOCKET, SO_ERROR, &err, &len) && !err)) {
				freeaddrinfo(found);
				return 1;
			}
		}
		close(c->fd);
		c->fd = -1;
		if (c->result == NET_CANCELLED)
			break;
	}
	freeaddrinfo(found);
	fail(c, refused_private ? "that address is on the local network" : "couldn't connect");
	return 0;
}

static int start_tls(conn *c, const url_parts *u)
{
	SSL_CTX *ctx = tls_context();
	if (!ctx) {
		fail(c, "no certificate list: apk add ca-certificates");
		return 0;
	}
	c->ssl = SSL_new(ctx);
	if (!c->ssl || !SSL_set_fd(c->ssl, c->fd) || !SSL_set_tlsext_host_name(c->ssl, u->host)) {
		fail(c, "couldn't set up the secure connection");
		return 0;
	}
	struct in6_addr ignored;
	if (inet_pton(AF_INET, u->host, &ignored) == 1 || inet_pton(AF_INET6, u->host, &ignored) == 1)
		X509_VERIFY_PARAM_set1_ip_asc(SSL_get0_param(c->ssl), u->host);
	else
		SSL_set1_host(c->ssl, u->host);
	touch_deadline(c);
	for (;;) {
		ERR_clear_error();
		const int r = SSL_connect(c->ssl);
		if (r == 1)
			return 1;
		const int e = SSL_get_error(c->ssl, r);
		if (e == SSL_ERROR_WANT_READ) {
			if (!wait_ready(c, POLLIN))
				return 0;
		} else if (e == SSL_ERROR_WANT_WRITE) {
			if (!wait_ready(c, POLLOUT))
				return 0;
		} else {
			const long verify = SSL_get_verify_result(c->ssl);
			if (verify != X509_V_OK) {
				char why[140];
				snprintf(why, sizeof(why), "certificate refused: %s", X509_verify_cert_error_string(verify));
				fail(c, why);
			} else {
				fail(c, "the secure connection failed");
			}
			return 0;
		}
	}
}

static int send_all(conn *c, const char *data, size_t n)
{
	size_t done = 0;
	touch_deadline(c);
	while (done < n) {
		if (c->ssl) {
			ERR_clear_error();
			const int r = SSL_write(c->ssl, data + done, (int)(n - done > 65536 ? 65536 : n - done));
			if (r > 0) {
				done += (size_t)r;
				continue;
			}
			const int e = SSL_get_error(c->ssl, r);
			if ((e != SSL_ERROR_WANT_READ && e != SSL_ERROR_WANT_WRITE) || !wait_ready(c, e == SSL_ERROR_WANT_READ ? POLLIN : POLLOUT)) {
				fail(c, "the connection dropped while sending");
				return 0;
			}
		} else {
			const ssize_t r = send(c->fd, data + done, n - done, MSG_NOSIGNAL);
			if (r > 0) {
				done += (size_t)r;
			} else if (r < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
				if (!wait_ready(c, POLLOUT))
					return 0;
			} else if (r < 0 && errno != EINTR) {
				fail(c, "the connection dropped while sending");
				return 0;
			}
		}
	}
	return 1;
}

/* Bytes received; 0 at the end; -1 with the reason recorded. */
static ssize_t recv_some(conn *c, char *buf, size_t cap)
{
	touch_deadline(c);
	for (;;) {
		if (c->ssl) {
			ERR_clear_error();
			const int r = SSL_read(c->ssl, buf, (int)cap);
			if (r > 0)
				return r;
			const int e = SSL_get_error(c->ssl, r);
			if (e == SSL_ERROR_ZERO_RETURN)
				return 0;
			if (e == SSL_ERROR_WANT_READ || e == SSL_ERROR_WANT_WRITE) {
				if (!wait_ready(c, e == SSL_ERROR_WANT_READ ? POLLIN : POLLOUT))
					return -1;
				continue;
			}
			fail(c, "the connection dropped");
			return -1;
		}
		const ssize_t r = recv(c->fd, buf, cap, 0);
		if (r >= 0)
			return r;
		if (errno == EAGAIN || errno == EWOULDBLOCK) {
			if (!wait_ready(c, POLLIN))
				return -1;
		} else if (errno != EINTR) {
			fail(c, "the connection dropped");
			return -1;
		}
	}
}

/* The value of a header in the head text, trimmed, or 0 if it's not there. */
static int head_value(const char *head, const char *name, char *out, size_t cap)
{
	const size_t name_n = strlen(name);
	for (const char *line = strstr(head, "\r\n"); line; line = strstr(line, "\r\n")) {
		line += 2;
		if (!strncasecmp(line, name, name_n) && line[name_n] == ':') {
			const char *v = line + name_n + 1;
			while (*v == ' ' || *v == '\t')
				v++;
			const char *end = strstr(v, "\r\n");
			size_t n = end ? (size_t)(end - v) : strlen(v);
			if (n >= cap)
				n = cap - 1;
			memcpy(out, v, n);
			out[n] = '\0';
			return 1;
		}
	}
	return 0;
}

static void deliver(conn *c, const char *data, size_t n)
{
	const net_request *q = c->req;
	if (q->on_data) {
		q->on_data(q->ctx, data, n, c->resp->status);
		return;
	}
	if (q->max_body && c->resp->body.n + n > q->max_body) {
		fail(c, "that page is too big for this phone");
		return;
	}
	sb_add(&c->resp->body, data, n);
	if (q->on_progress)
		q->on_progress(q->ctx, c->resp->body.n);
}

/* The body as its chunks arrive. */
typedef struct {
	int in_size, in_trailer, done;
	unsigned long long left;
	char line[CHUNK_LINE];
	int line_n;
	int skip_crlf;
} chunks;

static void feed_chunks(conn *c, chunks *k, const char *data, size_t n)
{
	size_t i = 0;
	while (i < n && !k->done && c->result == NET_OK) {
		if (k->skip_crlf) {
			if (data[i] == '\n')
				k->skip_crlf = 0;
			i++;
		} else if (k->left) {
			const size_t take = (unsigned long long)(n - i) < k->left ? n - i : (size_t)k->left;
			deliver(c, data + i, take);
			i += take;
			k->left -= take;
			if (!k->left)
				k->skip_crlf = 1;
		} else {
			const char ch = data[i++];
			if (ch != '\n') {
				if (k->line_n < CHUNK_LINE - 1)
					k->line[k->line_n++] = ch;
				continue;
			}
			k->line[k->line_n] = '\0';
			k->line_n = 0;
			char *end;
			const unsigned long long size = strtoull(k->line, &end, 16);
			if (end == k->line) {
				fail(c, "the server's answer was garbled");
				return;
			}
			if (!size)
				k->done = 1;
			k->left = size;
		}
	}
}

static void read_response(conn *c)
{
	net_response *resp = c->resp;
	enum { BUF = 16 * 1024 };
	char *buf = malloc(BUF);
	sb head = { 0 };
	size_t body_at = 0;
	if (!buf)
		abort();
	while (!body_at) {
		const ssize_t r = recv_some(c, buf, BUF);
		if (r < 0)
			goto out;
		if (!r) {
			fail(c, "the server hung up without answering");
			goto out;
		}
		sb_add(&head, buf, (size_t)r);
		const char *end = strstr(head.s, "\r\n\r\n");
		if (end)
			body_at = (size_t)(end - head.s) + 4;
		else if (head.n > HEAD_MAX) {
			fail(c, "the server's answer was garbled");
			goto out;
		}
	}
	if (sscanf(head.s, "HTTP/%*d.%*d %d", &resp->status) != 1 && sscanf(head.s, "HTTP/%*d %d", &resp->status) != 1) {
		fail(c, "that isn't a web server");
		goto out;
	}
	const size_t extra = head.n - body_at;
	head.s[body_at - 2] = '\0';
	char value[128];
	head_value(head.s, "Content-Type", resp->content_type, sizeof(resp->content_type));
	head_value(head.s, "Location", resp->location, sizeof(resp->location));
	if (head_value(head.s, "Content-Encoding", value, sizeof(value)) && strcasestr(value, "gzip"))
		resp->gzipped = 1;
	const int chunked = head_value(head.s, "Transfer-Encoding", value, sizeof(value)) && strcasestr(value, "chunked");
	long long remaining = -1;
	if (!chunked && head_value(head.s, "Content-Length", value, sizeof(value)))
		remaining = strtoll(value, NULL, 10);
	if (resp->status >= 300 && resp->status < 400 && resp->location[0])
		goto out;              /* the redirect is all we want */

	chunks k = { 0 };
	const char *pending = head.s + body_at;
	size_t pending_n = extra;
	while (c->result == NET_OK) {
		if (pending_n) {
			if (chunked) {
				feed_chunks(c, &k, pending, pending_n);
				if (k.done)
					break;
			} else {
				const size_t take = remaining >= 0 && (long long)pending_n > remaining ? (size_t)remaining : pending_n;
				deliver(c, pending, take);
				if (remaining >= 0) {
					remaining -= (long long)take;
				}
			}
		}
		if (!remaining)
			break;
		const ssize_t r = recv_some(c, buf, BUF);
		if (r < 0)
			break;
		if (!r) {
			if (chunked || remaining > 0)
				fail(c, "the connection dropped part way through");
			break;
		}
		pending = buf;
		pending_n = (size_t)r;
	}
out:
	sb_free(&head);
	free(buf);
}

int net_fetch(const net_request *req, net_response *resp)
{
	memset(resp, 0, sizeof(*resp));
	conn c = { .req = req, .resp = resp, .fd = -1 };
	url_parts u;
	if (!url_parse(req->url, &u)) {
		fail(&c, "that isn't a web address");
		return c.result;
	}
	touch_deadline(&c);
	if (open_socket(&c, &u) && (!u.secure || start_tls(&c, &u))) {
		sb head = { 0 };
		char line[256];
		sb_adds(&head, req->method ? req->method : "GET");
		sb_adds(&head, " ");
		sb_adds(&head, u.path);
		sb_adds(&head, " HTTP/1.1\r\nHost: ");
		sb_adds(&head, strchr(u.host, ':') ? "[" : "");
		sb_adds(&head, u.host);
		sb_adds(&head, strchr(u.host, ':') ? "]" : "");
		if (u.port != (u.secure ? 443 : 80)) {
			snprintf(line, sizeof(line), ":%d", u.port);
			sb_adds(&head, line);
		}
		sb_adds(&head, "\r\nUser-Agent: Mozilla/5.0 (Linux; Android 4.4; Mobile; TREND OS) webd/1.0\r\nAccept: */*\r\nConnection: close\r\n");
		if (req->gzip)
			sb_adds(&head, "Accept-Encoding: gzip\r\n");
		if (req->headers)
			sb_adds(&head, req->headers);
		if (req->body) {
			snprintf(line, sizeof(line), "Content-Length: %zu\r\n", req->body_n);
			sb_adds(&head, line);
		}
		sb_adds(&head, "\r\n");
		if (send_all(&c, head.s, head.n) && (!req->body || send_all(&c, req->body, req->body_n)))
			read_response(&c);
		memset(head.s, 0, head.n);     /* it may hold the API key */
		sb_free(&head);
	}
	if (c.ssl) {
		SSL_free(c.ssl);
	}
	if (c.fd >= 0)
		close(c.fd);
	return c.result;
}

void net_response_free(net_response *resp)
{
	sb_free(&resp->body);
}
