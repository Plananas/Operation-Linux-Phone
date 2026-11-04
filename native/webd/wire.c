#include "wire.h"

#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void write_all(const unsigned char *p, size_t n)
{
	while (n) {
		const ssize_t w = write(STDOUT_FILENO, p, n);
		if (w < 0) {
			if (errno == EINTR)
				continue;
			_exit(0);      /* the shell has gone */
		}
		p += w;
		n -= (size_t)w;
	}
}

static void frame(int kind, const void *a, size_t a_n, const void *b, size_t b_n)
{
	const size_t n = a_n + b_n;
	const unsigned char head[4] = { (unsigned char)kind, (unsigned char)n, (unsigned char)(n >> 8), (unsigned char)(n >> 16) };
	write_all(head, 4);
	if (a_n)
		write_all(a, a_n);
	if (b_n)
		write_all(b, b_n);
}

void wire_reset(void)
{
	frame(WEB_F_RESET, NULL, 0, NULL, 0);
}

void wire_row(int index, const doc_row *row)
{
	const unsigned char at[2] = { (unsigned char)index, (unsigned char)(index >> 8) };
	frame(WEB_F_ROW, at, 2, row->b, row->len);
}

void wire_rows(int count)
{
	const unsigned char at[2] = { (unsigned char)count, (unsigned char)(count >> 8) };
	frame(WEB_F_ROWS, at, 2, NULL, 0);
}

void wire_addr(int secure, const char *address)
{
	const unsigned char flag = (unsigned char)secure;
	frame(WEB_F_ADDR, &flag, 1, address, strlen(address));
}

void wire_status(int state, const char *text)
{
	const unsigned char flag = (unsigned char)state;
	frame(WEB_F_STATUS, &flag, 1, text, strlen(text));
}

void wire_scroll(unsigned px)
{
	const unsigned char v[4] = { (unsigned char)px, (unsigned char)(px >> 8), (unsigned char)(px >> 16), (unsigned char)(px >> 24) };
	frame(WEB_F_SCROLL, v, 4, NULL, 0);
}

void wire_open(const char *url)
{
	frame(WEB_F_OPEN, url, strlen(url), NULL, 0);
}

void cmd_fill(cmd_reader *r, int wait)
{
	struct pollfd p = { STDIN_FILENO, POLLIN, 0 };
	if (r->closed || poll(&p, 1, wait ? -1 : 0) <= 0)
		return;
	if (r->n == sizeof(r->buf))
		r->n = 0;              /* one absurdly long line: drop it */
	const ssize_t got = read(STDIN_FILENO, r->buf + r->n, sizeof(r->buf) - r->n);
	if (got > 0)
		r->n += (size_t)got;
	else if (got == 0)
		r->closed = 1;
}

int cmd_next(cmd_reader *r, char *out, size_t cap)
{
	const char *nl = memchr(r->buf, '\n', r->n);
	if (!nl)
		return 0;
	const size_t len = (size_t)(nl - r->buf);
	const size_t keep = len < cap - 1 ? len : cap - 1;
	memcpy(out, r->buf, keep);
	out[keep] = '\0';
	r->n -= len + 1;
	memmove(r->buf, nl + 1, r->n);
	return 1;
}
