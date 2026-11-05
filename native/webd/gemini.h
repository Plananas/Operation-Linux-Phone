/* The Gemini API's words, and nothing else: what a request looks like and what a streamed reply means. Pure, so
 * that it can be tested without a network. The turn itself, and the tools, are in agent.c. */
#ifndef WEBD_GEMINI_H
#define WEBD_GEMINI_H

#include <stddef.h>

#include "doc.h"

enum { GEMINI_MAX_CALLS = 16 };

typedef struct {
	sb name, id, args;             /* args is JSON text; id is often empty */
} gemini_call;

/* One reply as its chunks come in. Zero it to start. */
typedef struct {
	sb text;                       /* what's for the screen, so far */
	sb parts;                      /* the reply's parts as received, comma-separated, to send back as they were */
	gemini_call calls[GEMINI_MAX_CALLS];
	int n_calls, too_many_calls, blocked;
	sb finish;                     /* finishReason, once it's come */
	sb error;
} gemini_reply;

typedef enum { GEMINI_DONE, GEMINI_CALLS, GEMINI_CUT_OFF, GEMINI_DECLINED, GEMINI_FAILED } gemini_outcome;

/* Take in one chunk's JSON. Bad JSON from the network just adds nothing. */
void gemini_read_chunk(const char *js, size_t n, gemini_reply *r);
gemini_outcome gemini_outcome_of(const gemini_reply *r);
void gemini_reply_clear(gemini_reply *r);

/* The conversation is the JSON text of the contents array, comma-separated, and only ever added to. */
void gemini_add_user(sb *contents, const char *text, size_t n);
void gemini_add_model(sb *contents, const gemini_reply *r);
/* Answers to one reply's calls go together: add_result for each, then add_results with them all. */
void gemini_add_result(sb *results, const gemini_call *call, const char *text, size_t n, int ok);
void gemini_add_results(sb *contents, const sb *results);

void gemini_body(sb *body, const char *system, const char *tools, const sb *contents);

#endif
