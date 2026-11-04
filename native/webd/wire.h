/* Saying things to the shell: see trend/apps/web_wire.h. */
#ifndef WEBD_WIRE_H
#define WEBD_WIRE_H

#include "doc.h"

void wire_reset(void);
void wire_row(int index, const doc_row *row);
void wire_rows(int count);
void wire_addr(int secure, const char *address);
void wire_status(int state, const char *text);
void wire_scroll(unsigned px);
void wire_open(const char *url);

/* Commands from the shell: one line each, on stdin. */
typedef struct {
	char buf[16384];
	size_t n;
	int closed;
} cmd_reader;

/* Read what's waiting (blocks if nothing is and wait is set). */
void cmd_fill(cmd_reader *r, int wait);
/* The next whole line into out, without its newline. 0 if there isn't one. */
int cmd_next(cmd_reader *r, char *out, size_t cap);

#endif
