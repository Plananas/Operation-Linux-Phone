/* filesd: the web server behind the Files app. It lets a browser on the home network list, fetch, add
 * and remove files in a few named folders, and nothing else.
 *
 * It's a separate process because it reads whatever the network sends it. It starts as root only to
 * bind port 80, then gives up root for good and runs as its own user, which owns just the shared
 * folders. A bug here can't take the shell down with it, or reach the rest of the phone through root.
 *
 * Nobody gets in without the PIN on the phone's screen. Every start makes a new PIN, and ten wrong
 * guesses shut the server down. Names are checked one path component at a time and folders are opened
 * with O_NOFOLLOW, so a request can't climb out of a shared folder, even through a symlink.
 *
 * Each connection gets a thread and one request. The state is in one struct behind one lock. The
 * shell starts this program, reads its status lines from stdout (the format is in trend/apps/files.h),
 * and stops it with SIGTERM.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <grp.h>
#include <inttypes.h>
#include <net/if.h>
#include <netinet/in.h>
#include <poll.h>
#include <pthread.h>
#include <pwd.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/sendfile.h>
#include <sys/signalfd.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>

#include "http.h"

enum {
	MAX_ROOTS = 4, MAX_CONNS = 16, MAX_SESSIONS = 8, MAX_FAILURES = 10, MAX_LIST = 10000, MAX_DEPTH = 32,
	HEAD_MAX = 8192, IO_BUF = 65536, SEND_CHUNK = 262144, STACK = 262144,
	TOKEN_BYTES = 16, TOKEN_HEX = TOKEN_BYTES * 2, PIN_DIGITS = 6,
	N_SLOTS = 5, NAME_CAP = 256,
	HEAD_SECONDS = 15, SOCKET_SECONDS = 30, IDLE_SECONDS = 30 * 60, REFRESH_SECONDS = 5,
};

#define RESERVE_BYTES (INT64_C(64) << 20)      /* always leave this much of the disk free */
#define COOKIE "trend_session"
#define COMMON_HEADERS "Connection: close\r\nX-Content-Type-Options: nosniff\r\n" \
		       "Cache-Control: no-store\r\nReferrer-Policy: no-referrer\r\n"
#define PAGE_POLICY "Content-Security-Policy: default-src 'none'; script-src 'unsafe-inline'; " \
		    "style-src 'unsafe-inline'; font-src 'self'; connect-src 'self'; form-action 'none'; " \
		    "base-uri 'none'; frame-ancestors 'none'\r\n"

typedef struct {
	char name[NAME_CAP];
	int fd;
} shared_root;

typedef struct {
	int used, sending, active, failed;
	int64_t done, total;
	char name[NAME_CAP];
} xfer_slot;

typedef struct {
	char *data;
	size_t len;
} asset;

typedef struct {
	pthread_mutex_t lock;
	shared_root roots[MAX_ROOTS];
	int n_roots, tmp_fd, random_fd, port;
	asset page, font;
	char pin[PIN_DIGITS + 1];
	char sessions[MAX_SESSIONS][TOKEN_HEX + 1];
	int next_session, failures, conns, active_xfers, dirty;
	int64_t reserved;
	time_t last_activity;
	const char *stop_reason;       /* non-NULL once the server should shut down */
	xfer_slot slots[N_SLOTS];
	uint64_t slot_clock;
	uint64_t slot_age[N_SLOTS];
} server;

typedef struct {
	server *s;
	int fd;
	char *buf;
} conn;

static time_t now_seconds(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec;
}

/* ---- sockets and responses ---- */

static int send_all(int fd, const void *data, size_t n)
{
	const char *p = data;
	while (n) {
		const ssize_t r = send(fd, p, n, MSG_NOSIGNAL);
		if (r < 0 && errno == EINTR)
			continue;
		if (r <= 0)
			return -1;
		p += r;
		n -= (size_t)r;
	}
	return 0;
}

static int send_head(int fd, int code, const char *reason, const char *type, const char *extra, int64_t length)
{
	char head[2048], len[48] = "";
	if (length >= 0)
		snprintf(len, sizeof(len), "Content-Length: %" PRId64 "\r\n", length);
	const int n = snprintf(head, sizeof(head), "HTTP/1.1 %d %s\r\n" COMMON_HEADERS "Content-Type: %s\r\n%s%s\r\n",
			       code, reason, type, len, extra ? extra : "");
	return n > 0 && (size_t)n < sizeof(head) ? send_all(fd, head, (size_t)n) : -1;
}

static void respond(int fd, int code, const char *reason, const char *type, const char *extra, const void *body, size_t n)
{
	if (!send_head(fd, code, reason, type, extra, (int64_t)n) && n)
		send_all(fd, body, n);
}

static void reply_text(int fd, int code, const char *reason, const char *text)
{
	respond(fd, code, reason, "text/plain; charset=utf-8", NULL, text, strlen(text));
}

/* Closing with unread data resets the connection, and the browser would lose the reply. So stop
 * sending, then read and discard for a moment. */
static void drain(int fd)
{
	static const int LIMIT = 1 << 20;
	char scrap[4096];
	const struct timeval wait = { 2, 0 };
	setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &wait, sizeof(wait));
	shutdown(fd, SHUT_WR);
	for (int total = 0; total < LIMIT;) {
		const ssize_t r = recv(fd, scrap, sizeof(scrap), 0);
		if (r <= 0)
			break;
		total += (int)r;
	}
}

static void reply_errno(int fd, int err)
{
	switch (err) {
	case EINVAL: case ENAMETOOLONG:
		reply_text(fd, 400, "Bad Request", "That name isn't allowed.");
		break;
	case ENOENT: case ENOTDIR: case ELOOP:
		reply_text(fd, 404, "Not Found", "Not found.");
		break;
	case EEXIST: case ENOTEMPTY: case EISDIR:
		reply_text(fd, 409, "Conflict", "That can't be done to what's there now.");
		break;
	case EACCES: case EPERM:
		reply_text(fd, 403, "Forbidden", "The server isn't allowed to do that.");
		break;
	case ENOSPC: case EDQUOT:
		reply_text(fd, 507, "Insufficient Storage", "The phone is full.");
		break;
	default:
		reply_text(fd, 500, "Internal Server Error", "Something went wrong on the phone.");
		break;
	}
}

/* ---- shared state ---- */

static int64_t disk_free(int fd)
{
	struct statvfs v;
	return fstatvfs(fd, &v) ? 0 : (int64_t)v.f_bavail * (int64_t)v.f_frsize;
}

static void touch_activity(server *s)
{
	pthread_mutex_lock(&s->lock);
	s->last_activity = now_seconds();
	pthread_mutex_unlock(&s->lock);
}

/* Shown on the phone: claims the oldest finished slot. -1 if all are busy; the transfer still works. */
static int xfer_begin(server *s, const char *name, int sending, int64_t total)
{
	pthread_mutex_lock(&s->lock);
	int best = -1;
	for (int i = 0; i < N_SLOTS; i++)
		if (!s->slots[i].active && (best < 0 || s->slot_age[i] < s->slot_age[best]))
			best = i;
	if (best >= 0) {
		xfer_slot *x = &s->slots[best];
		x->used = 1;
		x->sending = sending;
		x->active = 1;
		x->failed = 0;
		x->done = 0;
		x->total = total;
		snprintf(x->name, sizeof(x->name), "%s", name);
		s->slot_age[best] = ++s->slot_clock;
	}
	s->active_xfers++;
	s->dirty = 1;
	s->last_activity = now_seconds();
	pthread_mutex_unlock(&s->lock);
	return best;
}

static void xfer_progress(server *s, int slot, int64_t done)
{
	pthread_mutex_lock(&s->lock);
	if (slot >= 0)
		s->slots[slot].done = done;
	s->dirty = 1;
	s->last_activity = now_seconds();
	pthread_mutex_unlock(&s->lock);
}

static void xfer_end(server *s, int slot, int failed)
{
	pthread_mutex_lock(&s->lock);
	if (slot >= 0) {
		s->slots[slot].active = 0;
		s->slots[slot].failed = failed;
	}
	s->active_xfers--;
	s->dirty = 1;
	s->last_activity = now_seconds();
	pthread_mutex_unlock(&s->lock);
}

/* ---- sessions ---- */

static int random_bytes(const server *s, void *out, size_t n)
{
	char *p = out;
	while (n) {
		const ssize_t r = read(s->random_fd, p, n);
		if (r <= 0)
			return -1;
		p += r;
		n -= (size_t)r;
	}
	return 0;
}

static int random_hex(const server *s, char *out, int n_bytes)
{
	unsigned char raw[TOKEN_BYTES];
	if (n_bytes > TOKEN_BYTES || random_bytes(s, raw, (size_t)n_bytes))
		return -1;
	for (int i = 0; i < n_bytes; i++)
		snprintf(out + i * 2, 3, "%02x", raw[i]);
	return 0;
}

/* Takes the same time wherever the first difference is. */
static int same_secret(const char *a, const char *b, size_t n)
{
	unsigned char diff = 0;
	for (size_t i = 0; i < n; i++)
		diff |= (unsigned char)(a[i] ^ b[i]);
	return diff == 0;
}

static int is_authed(server *s, const http_req *req)
{
	char value[TOKEN_HEX + 2];
	if (!req->cookie || http_cookie_value(req->cookie, COOKIE, value, sizeof(value)) ||
	    strlen(value) != TOKEN_HEX)
		return 0;
	int found = 0;
	pthread_mutex_lock(&s->lock);
	for (int i = 0; i < MAX_SESSIONS; i++)
		found |= s->sessions[i][0] != '\0' && same_secret(s->sessions[i], value, TOKEN_HEX);
	pthread_mutex_unlock(&s->lock);
	return found;
}

/* Read a short request body into out as a string. */
static int read_small_body(const conn *c, const http_req *req, const char *have, size_t n_have, char *out, size_t cap)
{
	if (req->content_length < 0 || req->content_length >= (int64_t)cap)
		return -1;
	const size_t want = (size_t)req->content_length;
	size_t got = n_have < want ? n_have : want;
	memcpy(out, have, got);
	while (got < want) {
		const ssize_t r = recv(c->fd, out + got, want - got, 0);
		if (r <= 0)
			return -1;
		got += (size_t)r;
	}
	out[got] = '\0';
	return 0;
}

static void handle_login(const conn *c, const http_req *req, const char *have, size_t n_have)
{
	server *s = c->s;
	char body[32], token[TOKEN_HEX + 1];
	if (read_small_body(c, req, have, n_have, body, sizeof(body))) {
		reply_text(c->fd, 400, "Bad Request", "Bad PIN.");
		return;
	}
	if (random_hex(s, token, TOKEN_BYTES)) {
		reply_errno(c->fd, EIO);
		return;
	}
	const int right = strlen(body) == PIN_DIGITS && same_secret(body, s->pin, PIN_DIGITS);
	pthread_mutex_lock(&s->lock);
	int lockout = 0;
	if (right) {
		memcpy(s->sessions[s->next_session], token, sizeof(token));
		s->next_session = (s->next_session + 1) % MAX_SESSIONS;
		s->last_activity = now_seconds();
	} else {
		lockout = ++s->failures >= MAX_FAILURES;
		if (lockout && !s->stop_reason)
			s->stop_reason = "too many wrong PINs";
	}
	pthread_mutex_unlock(&s->lock);

	if (right) {
		char cookie[128];
		snprintf(cookie, sizeof(cookie), "Set-Cookie: " COOKIE "=%s; HttpOnly; SameSite=Strict; Path=/\r\n", token);
		respond(c->fd, 200, "OK", "text/plain; charset=utf-8", cookie, "ok", 2);
	} else {
		reply_text(c->fd, 403, "Forbidden", lockout ? "Too many wrong PINs. Sharing has stopped." : "Wrong PIN.");
	}
}

/* ---- paths ---- */

/* Walk a raw URL path like "music/sub%20dir/a.mp3" down from a shared folder, one checked component
 * at a time. Returns the open folder. With leaf != NULL the last component isn't opened: it's put in
 * leaf, and there must be one. Returns -1 with errno set. */
static int walk(const server *s, const char *path, char *leaf)
{
	char name[NAME_CAP];
	int fd = -1;
	/* A fresh open each time, never a dup: a dup would share its reading position, so a listing would
	 * begin wherever the last one finished. */
	for (int depth = 0;; depth++) {
		const char *slash = strchr(path, '/');
		const size_t len = slash ? (size_t)(slash - path) : strlen(path);
		if (depth > MAX_DEPTH || http_decode(path, len, name, sizeof(name)) < 0 || !fs_name_ok(name)) {
			errno = EINVAL;
			goto fail;
		}
		if (depth == 0) {
			for (int i = 0; i < s->n_roots && fd < 0; i++)
				if (!strcmp(s->roots[i].name, name))
					fd = openat(s->roots[i].fd, ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
			if (fd < 0) {
				errno = ENOENT;
				return -1;
			}
		} else if (!slash && leaf) {
			memcpy(leaf, name, strlen(name) + 1);
			return fd;
		} else {
			const int next = openat(fd, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
			if (next < 0)
				goto fail;
			close(fd);
			fd = next;
		}
		if (!slash) {
			if (leaf) {            /* a shared folder itself can't be a leaf */
				errno = EINVAL;
				goto fail;
			}
			return fd;
		}
		path = slash + 1;
	}
fail:;
	const int err = errno;
	if (fd >= 0)
		close(fd);
	errno = err;
	return -1;
}

/* ---- listing ---- */

typedef struct {
	int fd, failed;
	size_t n;
	char buf[8192];
} out_stream;

static void out_flush(out_stream *o)
{
	if (!o->failed && o->n && send_all(o->fd, o->buf, o->n))
		o->failed = 1;
	o->n = 0;
}

static void out_printf(out_stream *o, const char *fmt, ...)
{
	if (o->n + 2048 > sizeof(o->buf))
		out_flush(o);
	va_list ap;
	va_start(ap, fmt);
	const int w = vsnprintf(o->buf + o->n, sizeof(o->buf) - o->n, fmt, ap);
	va_end(ap);
	if (w > 0)
		o->n += (size_t)w;
}

static void out_entry(out_stream *o, int *first, const char *name, int is_dir, int64_t size, int64_t mtime)
{
	char escaped[NAME_CAP * 6];
	if (json_escape(name, escaped, sizeof(escaped)) < 0)
		return;
	out_printf(o, "%s{\"name\":\"%s\",\"dir\":%d,\"size\":%" PRId64 ",\"mtime\":%" PRId64 "}",
		   *first ? "" : ",", escaped, is_dir, size, mtime);
	*first = 0;
}

static void handle_list(const conn *c, const char *path)
{
	const server *s = c->s;
	DIR *dir = NULL;
	if (*path) {
		const int fd = walk(s, path, NULL);
		dir = fd < 0 ? NULL : fdopendir(fd);
		if (!dir) {
			const int err = errno;
			if (fd >= 0)
				close(fd);
			reply_errno(c->fd, err);
			return;
		}
	}
	if (send_head(c->fd, 200, "OK", "application/json", NULL, -1)) {
		if (dir)
			closedir(dir);
		return;
	}
	out_stream *o = malloc(sizeof(*o));
	if (!o) {
		if (dir)
			closedir(dir);
		return;
	}
	o->fd = c->fd;
	o->failed = 0;
	o->n = 0;
	out_printf(o, "{\"free\":%" PRId64 ",\"entries\":[", disk_free(s->tmp_fd));
	int first = 1;
	if (dir) {
		const struct dirent *e;
		for (int count = 0; (e = readdir(dir)) && count < MAX_LIST && !o->failed;) {
			struct stat st;
			if (!fs_name_ok(e->d_name) || fstatat(dirfd(dir), e->d_name, &st, AT_SYMLINK_NOFOLLOW))
				continue;
			if (!S_ISREG(st.st_mode) && !S_ISDIR(st.st_mode))
				continue;
			out_entry(o, &first, e->d_name, S_ISDIR(st.st_mode), (int64_t)st.st_size, (int64_t)st.st_mtime);
			count++;
		}
		closedir(dir);
	} else {
		for (int i = 0; i < s->n_roots; i++)
			out_entry(o, &first, s->roots[i].name, 1, 0, 0);
	}
	out_printf(o, "]}");
	out_flush(o);
	free(o);
}

/* ---- download ---- */

static void handle_get_file(const conn *c, const http_req *req, const char *path)
{
	server *s = c->s;
	char leaf[NAME_CAP], encoded[NAME_CAP * 3], extra[1200];
	const int parent = walk(s, path, leaf);
	if (parent < 0) {
		reply_errno(c->fd, errno);
		return;
	}
	const int fd = openat(parent, leaf, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
	const int open_err = errno;
	close(parent);
	if (fd < 0) {
		reply_errno(c->fd, open_err);
		return;
	}
	struct stat st;
	if (fstat(fd, &st) || !S_ISREG(st.st_mode) || http_encode_attr(leaf, encoded, sizeof(encoded)) < 0) {
		close(fd);
		reply_errno(c->fd, ENOENT);
		return;
	}
	const int64_t size = (int64_t)st.st_size;
	int64_t from = 0, to = size - 1;
	const int ranged = req->range ? http_parse_range(req->range, size, &from, &to) : 0;
	if (ranged < 0) {
		char bad[64];
		snprintf(bad, sizeof(bad), "Content-Range: bytes */%" PRId64 "\r\n", size);
		respond(c->fd, 416, "Range Not Satisfiable", "text/plain", bad, "", 0);
		close(fd);
		return;
	}
	if (!ranged) {
		from = 0;
		to = size - 1;
	}
	/* Always a download, and sandboxed even if something opens it: an uploaded page must never run
	 * as part of this site. */
	int n = snprintf(extra, sizeof(extra), "Accept-Ranges: bytes\r\nContent-Security-Policy: sandbox\r\n"
			 "Content-Disposition: attachment; filename*=UTF-8''%s\r\n", encoded);
	if (ranged)
		n += snprintf(extra + n, sizeof(extra) - (size_t)n, "Content-Range: bytes %" PRId64 "-%" PRId64 "/%" PRId64 "\r\n",
			      from, to, size);
	const int64_t length = to - from + 1;
	if (send_head(c->fd, ranged ? 206 : 200, ranged ? "Partial Content" : "OK", "application/octet-stream", extra, length)) {
		close(fd);
		return;
	}
	const int slot = xfer_begin(s, leaf, 1, length);
	off_t offset = (off_t)from;
	int64_t left = length;
	int failed = 0;
	while (left > 0) {
		const ssize_t r = sendfile(c->fd, fd, &offset, left < SEND_CHUNK ? (size_t)left : SEND_CHUNK);
		if (r < 0 && errno == EINTR)
			continue;
		if (r <= 0) {
			failed = 1;
			break;
		}
		left -= r;
		xfer_progress(s, slot, length - left);
	}
	xfer_end(s, slot, failed);
	close(fd);
}

/* ---- upload ---- */

/* Claim disk space for an upload, so several at once can't overrun what's free. */
static int reserve_space(server *s, int64_t bytes)
{
	const int64_t free_now = disk_free(s->tmp_fd);
	pthread_mutex_lock(&s->lock);
	const int fits = bytes <= free_now - RESERVE_BYTES - s->reserved;
	if (fits)
		s->reserved += bytes;
	pthread_mutex_unlock(&s->lock);
	return fits ? 0 : -1;
}

static void release_space(server *s, int64_t bytes)
{
	pthread_mutex_lock(&s->lock);
	s->reserved -= bytes;
	pthread_mutex_unlock(&s->lock);
}

static int write_all(int fd, const char *p, size_t n)
{
	while (n) {
		const ssize_t r = write(fd, p, n);
		if (r < 0 && errno == EINTR)
			continue;
		if (r <= 0)
			return -1;
		p += r;
		n -= (size_t)r;
	}
	return 0;
}

/* Copy the request's body to fd. 0 if all of it arrived and was written; -1 with errno if not, where
 * ECONNRESET means the sender gave up. */
static int receive_body(const conn *c, int fd, int slot, int64_t length, const char *have, size_t n_have)
{
	int64_t done = 0;
	const size_t first = (int64_t)n_have < length ? n_have : (size_t)length;
	if (first && write_all(fd, have, first))
		return -1;
	done += (int64_t)first;
	while (done < length) {
		const int64_t left = length - done;
		char *space = c->buf + HEAD_MAX + 2;
		const ssize_t r = recv(c->fd, space, left < IO_BUF ? (size_t)left : IO_BUF, 0);
		if (r < 0 && errno == EINTR)
			continue;
		if (r <= 0) {
			errno = ECONNRESET;
			return -1;
		}
		if (write_all(fd, space, (size_t)r))
			return -1;
		done += r;
		xfer_progress(c->s, slot, done);
	}
	return 0;
}

static void handle_put_file(const conn *c, const http_req *req, const char *path, const char *have, size_t n_have)
{
	server *s = c->s;
	char leaf[NAME_CAP], tmp[TOKEN_HEX + 8] = "up-";
	if (req->content_length < 0) {
		reply_text(c->fd, 411, "Length Required", "The upload needs a length.");
		return;
	}
	const int parent = walk(s, path, leaf);
	if (parent < 0) {
		reply_errno(c->fd, errno);
		drain(c->fd);
		return;
	}
	if (reserve_space(s, req->content_length)) {
		close(parent);
		reply_errno(c->fd, ENOSPC);
		drain(c->fd);
		return;
	}
	int fd = -1, err = 0;
	if (random_hex(s, tmp + 3, 8)) {
		err = EIO;
	} else {
		fd = openat(s->tmp_fd, tmp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0644);
		if (fd < 0)
			err = errno;
	}
	if (fd < 0) {
		close(parent);
		release_space(s, req->content_length);
		reply_errno(c->fd, err);
		drain(c->fd);
		return;
	}
	if (req->expect && !strcasecmp(req->expect, "100-continue")) {
		static const char CONTINUE[] = "HTTP/1.1 100 Continue\r\n\r\n";
		send_all(c->fd, CONTINUE, sizeof(CONTINUE) - 1);
	}
	const int slot = xfer_begin(s, leaf, 0, req->content_length);
	int failed = receive_body(c, fd, slot, req->content_length, have, n_have);
	err = failed ? errno : 0;
	if (!failed && fsync(fd)) {
		failed = 1;
		err = errno;
	}
	close(fd);
	if (!failed && renameat(s->tmp_fd, tmp, parent, leaf)) {
		failed = 1;
		err = errno;
	}
	if (failed)
		unlinkat(s->tmp_fd, tmp, 0);
	close(parent);
	release_space(s, req->content_length);
	xfer_end(s, slot, failed);
	if (!failed) {
		respond(c->fd, 201, "Created", "text/plain", NULL, "", 0);
	} else if (err != ECONNRESET) {
		reply_errno(c->fd, err);
		drain(c->fd);
	}
}

/* ---- delete and new folder ---- */

static void handle_delete(const conn *c, const char *path)
{
	char leaf[NAME_CAP];
	const int parent = walk(c->s, path, leaf);
	if (parent < 0) {
		reply_errno(c->fd, errno);
		return;
	}
	struct stat st;
	int r = fstatat(parent, leaf, &st, AT_SYMLINK_NOFOLLOW);
	if (!r)
		r = unlinkat(parent, leaf, S_ISDIR(st.st_mode) ? AT_REMOVEDIR : 0);
	const int err = errno;
	close(parent);
	if (r)
		reply_errno(c->fd, err);
	else
		respond(c->fd, 200, "OK", "text/plain", NULL, "", 0);
}

static void handle_mkdir(const conn *c, const char *path)
{
	char leaf[NAME_CAP];
	const int parent = walk(c->s, path, leaf);
	if (parent < 0) {
		reply_errno(c->fd, errno);
		return;
	}
	const int r = mkdirat(parent, leaf, 0755);
	const int err = errno;
	close(parent);
	if (r)
		reply_errno(c->fd, err);
	else
		respond(c->fd, 201, "Created", "text/plain", NULL, "", 0);
}

/* ---- one request ---- */

/* The rest of target after prefix, or NULL if it doesn't start with it. */
static const char *after_prefix(const char *target, const char *prefix)
{
	const size_t n = strlen(prefix);
	return strncmp(target, prefix, n) ? NULL : target + n;
}

static void route(const conn *c, const http_req *req, const char *have, size_t n_have)
{
	server *s = c->s;
	const int get = !strcmp(req->method, "GET"), post = !strcmp(req->method, "POST");
	const int put = !strcmp(req->method, "PUT"), del = !strcmp(req->method, "DELETE");
	const char *rest;

	if (get && !strcmp(req->target, "/")) {
		respond(c->fd, 200, "OK", "text/html; charset=utf-8", PAGE_POLICY, s->page.data, s->page.len);
		return;
	}
	if (get && !strcmp(req->target, "/vt323.ttf")) {
		respond(c->fd, 200, "OK", "font/ttf", NULL, s->font.data, s->font.len);
		return;
	}
	if (!get && !req->same_origin_marker) {        /* other sites can't set this header */
		reply_text(c->fd, 403, "Forbidden", "Refused.");
		drain(c->fd);
		return;
	}
	if (post && !strcmp(req->target, "/api/login")) {
		handle_login(c, req, have, n_have);
		return;
	}
	if (!is_authed(s, req)) {
		reply_text(c->fd, 401, "Unauthorized", "Enter the PIN first.");
		drain(c->fd);
		return;
	}
	touch_activity(s);
	if (get && !strcmp(req->target, "/api/list"))
		handle_list(c, "");
	else if (get && (rest = after_prefix(req->target, "/api/list/")))
		handle_list(c, rest);
	else if (get && (rest = after_prefix(req->target, "/api/file/")))
		handle_get_file(c, req, rest);
	else if (put && (rest = after_prefix(req->target, "/api/file/")))
		handle_put_file(c, req, rest, have, n_have);
	else if (del && (rest = after_prefix(req->target, "/api/file/")))
		handle_delete(c, rest);
	else if (post && (rest = after_prefix(req->target, "/api/dir/")))
		handle_mkdir(c, rest);
	else
		reply_text(c->fd, 404, "Not Found", "Not found.");
}

static void handle_conn(const conn *c)
{
	const time_t deadline = now_seconds() + HEAD_SECONDS;
	size_t got = 0;
	ssize_t end = -1;
	while (end < 0) {
		if (got == HEAD_MAX) {
			reply_text(c->fd, 431, "Request Header Fields Too Large", "Too long.");
			return;
		}
		const ssize_t r = recv(c->fd, c->buf + got, HEAD_MAX - got, 0);
		if (r < 0 && errno == EINTR)
			continue;
		if (r <= 0 || now_seconds() > deadline)
			return;
		got += (size_t)r;
		end = http_head_end(c->buf, got);
	}
	/* The body's first bytes may have come with the head. Move them past the head, which stays in use
	 * for as long as the request does, and let uploads read into the space after that. */
	const size_t n_have = got - (size_t)end;
	char *have = c->buf + HEAD_MAX + 2;
	memmove(have, c->buf + end, n_have);
	c->buf[end - 2] = '\0';
	http_req req;
	if (http_parse_head(c->buf, &req)) {
		reply_text(c->fd, 400, "Bad Request", "Bad request.");
		return;
	}
	route(c, &req, have, n_have);
}

static void *conn_main(void *arg)
{
	conn *c = arg;
	handle_conn(c);
	close(c->fd);
	server *s = c->s;
	pthread_mutex_lock(&s->lock);
	s->conns--;
	pthread_mutex_unlock(&s->lock);
	free(c->buf);
	free(c);
	return NULL;
}

static void accept_one(server *s, int listen_fd, const pthread_attr_t *attr)
{
	const int fd = accept4(listen_fd, NULL, NULL, SOCK_CLOEXEC);
	if (fd < 0)
		return;
	const struct timeval wait = { SOCKET_SECONDS, 0 };
	setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &wait, sizeof(wait));
	setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &wait, sizeof(wait));

	pthread_mutex_lock(&s->lock);
	const int room = s->conns < MAX_CONNS;
	if (room)
		s->conns++;
	pthread_mutex_unlock(&s->lock);
	conn *c = room ? malloc(sizeof(*c)) : NULL;
	char *buf = c ? malloc(HEAD_MAX + 2 + IO_BUF) : NULL;
	pthread_t thread;
	if (buf) {
		*c = (conn){ s, fd, buf };
		if (!pthread_create(&thread, attr, conn_main, c))
			return;
	}
	if (!room) {
		reply_text(fd, 503, "Service Unavailable", "Busy.");
	} else {
		pthread_mutex_lock(&s->lock);
		s->conns--;
		pthread_mutex_unlock(&s->lock);
	}
	free(buf);
	free(c);
	close(fd);
}

/* ---- status for the shell ---- */

/* wlan0 if it has an address, otherwise anything that isn't loopback. */
static void find_address(char *out, size_t cap)
{
	struct ifaddrs *list;
	out[0] = '\0';
	if (getifaddrs(&list))
		return;
	for (const struct ifaddrs *a = list; a; a = a->ifa_next) {
		if (!a->ifa_addr || a->ifa_addr->sa_family != AF_INET || !(a->ifa_flags & IFF_UP) || (a->ifa_flags & IFF_LOOPBACK))
			continue;
		const int is_wifi = !strcmp(a->ifa_name, "wlan0");
		if (is_wifi || !out[0])
			inet_ntop(AF_INET, &((const struct sockaddr_in *)(const void *)a->ifa_addr)->sin_addr, out, (socklen_t)cap);
		if (is_wifi)
			break;
	}
	freeifaddrs(list);
}

/* Writes a whole snapshot in one go: under PIPE_BUF, so on a non-blocking pipe it goes in whole or not
 * at all. If the shell has gone away there's no one to stop us later, so stop now. */
static int emit_status(server *s, const char *address)
{
	char text[4000];
	size_t n = 0;
	pthread_mutex_lock(&s->lock);
	n += (size_t)snprintf(text + n, sizeof(text) - n, "U %s %d\nA %s\nF %" PRId64 "\n", s->pin, s->port, address, disk_free(s->tmp_fd));
	for (int i = 0; i < N_SLOTS; i++) {
		const xfer_slot *x = &s->slots[i];
		if (x->used)
			n += (size_t)snprintf(text + n, sizeof(text) - n, "T %d %c %c %" PRId64 " %" PRId64 " %s\n", i,
					      x->sending ? 'd' : 'u', x->active ? 'a' : x->failed ? 'x' : 'k', x->done, x->total, x->name);
	}
	s->dirty = 0;
	pthread_mutex_unlock(&s->lock);
	const ssize_t r = write(STDOUT_FILENO, text, n);
	return r < 0 && errno == EPIPE ? -1 : 0;
}

/* ---- starting up ---- */

static void say_stopped(const char *reason)
{
	char line[256];
	const int n = snprintf(line, sizeof(line), "X %s\n", reason);
	if (write(STDOUT_FILENO, line, (size_t)n) < 0)
		return;
}

static void give_up(const char *reason)
{
	say_stopped(reason);
	exit(1);
}

static int read_asset(const char *path, asset *out)
{
	const int fd = open(path, O_RDONLY | O_CLOEXEC);
	struct stat st;
	if (fd < 0 || fstat(fd, &st) || !(out->data = malloc((size_t)st.st_size + 1))) {
		if (fd >= 0)
			close(fd);
		return -1;
	}
	out->len = 0;
	while (out->len < (size_t)st.st_size) {
		const ssize_t r = read(fd, out->data + out->len, (size_t)st.st_size - out->len);
		if (r <= 0)
			break;
		out->len += (size_t)r;
	}
	close(fd);
	return out->len == (size_t)st.st_size ? 0 : -1;
}

/* The shared folder and everything in it belongs to the server's user, including files that arrived
 * by scp as root. */
static void chown_tree(int fd, uid_t uid, gid_t gid, int depth)
{
	if (fchown(fd, uid, gid) || depth > MAX_DEPTH)
		return;
	const int walk_fd = fcntl(fd, F_DUPFD_CLOEXEC, 0);
	DIR *dir = walk_fd < 0 ? NULL : fdopendir(walk_fd);
	if (!dir)
		return;
	rewinddir(dir);
	const struct dirent *e;
	while ((e = readdir(dir))) {
		if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, ".."))
			continue;
		struct stat st;
		if (fstatat(fd, e->d_name, &st, AT_SYMLINK_NOFOLLOW))
			continue;
		if (S_ISDIR(st.st_mode)) {
			const int sub = openat(fd, e->d_name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
			if (sub >= 0) {
				chown_tree(sub, uid, gid, depth + 1);
				close(sub);
			}
		} else if (fchownat(fd, e->d_name, uid, gid, AT_SYMLINK_NOFOLLOW)) {
			continue;
		}
	}
	closedir(dir);
}

/* For good: root, every group (so no new sockets on this kernel), and any way back. */
static void drop_root(const server *s, const char *user)
{
	const struct passwd *pw = getpwnam(user);
	if (!pw)
		give_up("no user for the server: run tools/deploy.sh");
	const uid_t uid = pw->pw_uid;
	const gid_t gid = pw->pw_gid;
	for (int i = 0; i < s->n_roots; i++)
		chown_tree(s->roots[i].fd, uid, gid, 0);
	chown_tree(s->tmp_fd, uid, gid, 0);
	if (setgroups(0, NULL) || setgid(gid) || setuid(uid) || setuid(0) == 0)
		give_up("couldn't give up root");
	prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0);
	prctl(PR_SET_DUMPABLE, 0, 0, 0, 0);
}

static void clean_tmp(int tmp_fd)
{
	const int walk_fd = fcntl(tmp_fd, F_DUPFD_CLOEXEC, 0);
	DIR *dir = walk_fd < 0 ? NULL : fdopendir(walk_fd);
	if (!dir)
		return;
	rewinddir(dir);
	const struct dirent *e;
	while ((e = readdir(dir)))
		if (!strncmp(e->d_name, "up-", 3))
			unlinkat(tmp_fd, e->d_name, 0);
	closedir(dir);
}

static int open_dir_making_it(const char *path)
{
	if (mkdir(path, 0755) && errno != EEXIST)
		return -1;
	return open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
}

/* A PIN of six digits, every value equally likely. */
static int make_pin(const server *s, char *out)
{
	static const uint32_t RANGE = 1000000, LIMIT = UINT32_MAX - UINT32_MAX % RANGE;
	uint32_t v;
	do {
		if (random_bytes(s, &v, sizeof(v)))
			return -1;
	} while (v >= LIMIT);
	snprintf(out, PIN_DIGITS + 1, "%06u", (unsigned)(v % RANGE));
	return 0;
}

static int open_listener(int port)
{
	const int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
	if (fd < 0)
		return -1;
	const int yes = 1;
	setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
	struct sockaddr_in addr = { .sin_family = AF_INET, .sin_port = htons((uint16_t)port), .sin_addr.s_addr = htonl(INADDR_ANY) };
	if (bind(fd, (const struct sockaddr *)&addr, sizeof(addr)) || listen(fd, 32)) {
		close(fd);
		return -1;
	}
	return fd;
}

static void add_root(server *s, const char *spec)
{
	const char *eq = strchr(spec, '=');
	if (!eq || s->n_roots == MAX_ROOTS || (size_t)(eq - spec) >= NAME_CAP)
		give_up("bad folder argument");
	shared_root *r = &s->roots[s->n_roots];
	memcpy(r->name, spec, (size_t)(eq - spec));
	r->name[eq - spec] = '\0';
	r->fd = open_dir_making_it(eq + 1);
	if (r->fd < 0 || !fs_name_ok(r->name))
		give_up("can't open a shared folder");
	s->n_roots++;
}

static void usage(void)
{
	fputs("filesd [-p port] [-u user] -w page.html -f font.ttf -t tmpdir name=folder ...\n", stderr);
	exit(2);
}

/* Serve until a signal, the idle limit, too many wrong PINs, or the shell going away. */
static void serve(server *s, int listen_fd, int signal_fd)
{
	pthread_attr_t attr;
	pthread_attr_init(&attr);
	pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
	pthread_attr_setstacksize(&attr, STACK);

	char address[64] = "";
	time_t last_refresh = 0;
	for (;;) {
		struct pollfd fds[2] = { { .fd = listen_fd, .events = POLLIN }, { .fd = signal_fd, .events = POLLIN } };
		const int ready = poll(fds, 2, 500);
		if (ready > 0 && (fds[1].revents & POLLIN))
			return;
		if (ready > 0 && (fds[0].revents & POLLIN))
			accept_one(s, listen_fd, &attr);

		const time_t now = now_seconds();
		pthread_mutex_lock(&s->lock);
		const char *reason = s->stop_reason;
		const int dirty = s->dirty;
		const int idle = s->active_xfers == 0 && s->conns == 0 && now - s->last_activity >= IDLE_SECONDS;
		pthread_mutex_unlock(&s->lock);
		if (!reason && idle)
			reason = "nothing happened for 30 minutes";
		if (reason) {
			say_stopped(reason);
			return;
		}
		const int refresh = now - last_refresh >= REFRESH_SECONDS;
		if (refresh) {
			find_address(address, sizeof(address));
			last_refresh = now;
		}
		if ((dirty || refresh) && emit_status(s, address))
			return;
	}
}

int main(int argc, char **argv)
{
	static server s;               /* big, and lives as long as the process; only main touches this name */
	const char *page = NULL, *font = NULL, *tmp = NULL, *user = NULL;
	int opt;
	s.port = 80;
	while ((opt = getopt(argc, argv, "p:u:w:f:t:")) != -1) {
		switch (opt) {
		case 'p': s.port = atoi(optarg); break;
		case 'u': user = optarg; break;
		case 'w': page = optarg; break;
		case 'f': font = optarg; break;
		case 't': tmp = optarg; break;
		default: usage();
		}
	}
	if (!page || !font || !tmp || optind == argc)
		usage();

	/* Signals arrive through a file descriptor, so nothing here needs a global for a handler. */
	sigset_t stop_signals;
	sigemptyset(&stop_signals);
	sigaddset(&stop_signals, SIGTERM);
	sigaddset(&stop_signals, SIGINT);
	pthread_sigmask(SIG_BLOCK, &stop_signals, NULL);
	const int signal_fd = signalfd(-1, &stop_signals, SFD_CLOEXEC);
	signal(SIGPIPE, SIG_IGN);
	fcntl(STDOUT_FILENO, F_SETFL, fcntl(STDOUT_FILENO, F_GETFL) | O_NONBLOCK);

	pthread_mutex_init(&s.lock, NULL);
	s.random_fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
	if (signal_fd < 0 || s.random_fd < 0)
		give_up("couldn't start");
	if (read_asset(page, &s.page) || read_asset(font, &s.font))
		give_up("web page is missing: run tools/deploy.sh");
	for (int i = optind; i < argc; i++)
		add_root(&s, argv[i]);
	s.tmp_fd = open_dir_making_it(tmp);
	if (s.tmp_fd < 0)
		give_up("can't open the temporary folder");
	const int listen_fd = open_listener(s.port);
	if (listen_fd < 0)
		give_up("the web port is in use");
	if (user) {
		drop_root(&s, user);
		prctl(PR_SET_PDEATHSIG, SIGTERM, 0, 0, 0);     /* after setuid, which clears it */
	}
	clean_tmp(s.tmp_fd);
	if (make_pin(&s, s.pin))
		give_up("no random numbers");
	s.last_activity = now_seconds();

	serve(&s, listen_fd, signal_fd);
	clean_tmp(s.tmp_fd);
	_exit(0);                      /* connection threads may still be running */
}
