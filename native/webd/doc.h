/* A document on its way to the screen: rows, the links and fields in them, and the word wrap that makes them.
 * Pure: nothing here does I/O. */
#ifndef WEBD_DOC_H
#define WEBD_DOC_H

#include <stddef.h>

#include "trend/apps/web_wire.h"

typedef struct {
	unsigned char len;
	unsigned char b[WEB_ROW_BYTES];
} doc_row;

enum { TARGET_LINK, TARGET_SUBMIT };

typedef struct {
	int kind;
	char *url;                     /* TARGET_LINK */
	int form;                      /* TARGET_SUBMIT */
	char *name, *value;            /* the submit button's own pair, if any */
} doc_target;

typedef struct {
	int form;
	char *name, *value;
	int row;                       /* where it's shown; -1 for hidden fields */
	int secret, width;
} doc_field;

typedef struct {
	char *action;
	int post;
} doc_form;

typedef struct {
	char *url;
	int row, n_rows;
	int done;
} doc_image;

typedef struct {
	doc_row *rows;
	int n, cap;
	doc_target *targets;
	int n_targets, cap_targets;
	doc_field *fields;
	int n_fields, cap_fields;
	doc_form *forms;
	int n_forms, cap_forms;
	doc_image *images;
	int n_images, cap_images;
	char *title;
	char *refresh;                 /* a <meta refresh> target */
} doc;

void doc_init(doc *d);
void doc_free(doc *d);
void doc_truncate(doc *d, int n_rows);
void doc_add_row(doc *d, const unsigned char *b, size_t n);
int doc_add_link(doc *d, const char *url);
int doc_add_submit(doc *d, int form, const char *name, const char *value);
int doc_add_form(doc *d, const char *action, int post);
int doc_add_field(doc *d, int form, const char *name, const char *value, int row, int secret, int width);
int doc_add_image(doc *d, const char *url, int row, int n_rows);
/* Redraw a field's row from its current value. */
void doc_field_row(doc *d, int field);
/* The plain characters of a row: control bytes gone, trailing newline added. Returns the length. */
size_t doc_row_text(const doc_row *r, char *out, size_t cap);

/* Word wrap. Text goes in as UTF-8 and comes out Latin-1, because that's what the font has. */
typedef struct {
	doc *d;
	int width, indent;
	unsigned char line[WEB_ROW_BYTES];
	int line_len, col;
	int started;                   /* the line has a word on it */
	unsigned char word[WEB_ROW_BYTES];
	int word_len;
	int space;                     /* a space is due before the next word */
	int style, link, field;        /* what the text being added should look like */
	int line_style, line_link;     /* what the line has been told so far */
	int pre;                       /* keep spaces and line breaks */
	int blank;                     /* the last row was empty, or there are none */
} flow;

void flow_init(flow *f, doc *d, int width);
void flow_text(flow *f, const char *s, size_t n);
void flow_codepoint(flow *f, unsigned cp);
void flow_style(flow *f, int style);
void flow_link(flow *f, int target);   /* -1 ends it */
void flow_break(flow *f);              /* finish the line, if one is started */
void flow_blank(flow *f);              /* finish the line and leave one empty row, once */
void flow_indent(flow *f, int cells);
void flow_end(flow *f);

/* Draw chat text: a little Markdown (headings, bullets, code, bold, links), since that's what models write. */
void doc_markdown(flow *f, const char *s, size_t n);

/* ---- growable strings ---- */
typedef struct {
	char *s;
	size_t n, cap;
} sb;

void sb_add(sb *b, const char *s, size_t n);
void sb_adds(sb *b, const char *s);
void sb_free(sb *b);

#endif
