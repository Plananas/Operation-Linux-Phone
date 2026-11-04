#define _GNU_SOURCE
#include "doc.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *dup_or_null(const char *s)
{
	return s ? strdup(s) : NULL;
}

void sb_add(sb *b, const char *s, size_t n)
{
	if (b->n + n + 1 > b->cap) {
		size_t cap = b->cap ? b->cap * 2 : 256;
		while (cap < b->n + n + 1)
			cap *= 2;
		char *grown = realloc(b->s, cap);
		if (!grown)
			abort();
		b->s = grown;
		b->cap = cap;
	}
	memcpy(b->s + b->n, s, n);
	b->n += n;
	b->s[b->n] = '\0';
}

void sb_adds(sb *b, const char *s)
{
	sb_add(b, s, strlen(s));
}

void sb_free(sb *b)
{
	free(b->s);
	memset(b, 0, sizeof(*b));
}

/* Make room for one more in a growable array. */
static void *room_for(void *items, int n, int *cap, size_t size)
{
	if (n < *cap)
		return items;
	const int next = *cap ? *cap * 2 : 16;
	void *grown = realloc(items, (size_t)next * size);
	if (!grown)
		abort();
	*cap = next;
	return grown;
}

void doc_init(doc *d)
{
	memset(d, 0, sizeof(*d));
}

void doc_free(doc *d)
{
	free(d->rows);
	for (int i = 0; i < d->n_targets; i++) {
		free(d->targets[i].url);
		free(d->targets[i].name);
		free(d->targets[i].value);
	}
	free(d->targets);
	for (int i = 0; i < d->n_fields; i++) {
		free(d->fields[i].name);
		free(d->fields[i].value);
	}
	free(d->fields);
	for (int i = 0; i < d->n_forms; i++)
		free(d->forms[i].action);
	free(d->forms);
	for (int i = 0; i < d->n_images; i++)
		free(d->images[i].url);
	free(d->images);
	free(d->title);
	free(d->refresh);
	doc_init(d);
}

void doc_truncate(doc *d, int n_rows)
{
	if (n_rows < d->n)
		d->n = n_rows;
}

void doc_add_row(doc *d, const unsigned char *b, size_t n)
{
	if (d->n >= WEB_MAX_ROWS)
		return;
	d->rows = room_for(d->rows, d->n, &d->cap, sizeof(doc_row));
	doc_row *r = &d->rows[d->n++];
	r->len = (unsigned char)(n > WEB_ROW_BYTES ? WEB_ROW_BYTES : n);
	memcpy(r->b, b, r->len);
}

int doc_add_link(doc *d, const char *url)
{
	d->targets = room_for(d->targets, d->n_targets, &d->cap_targets, sizeof(doc_target));
	d->targets[d->n_targets] = (doc_target){ .kind = TARGET_LINK, .url = strdup(url) };
	return d->n_targets++;
}

int doc_add_submit(doc *d, int form, const char *name, const char *value)
{
	d->targets = room_for(d->targets, d->n_targets, &d->cap_targets, sizeof(doc_target));
	d->targets[d->n_targets] = (doc_target){ .kind = TARGET_SUBMIT, .form = form,
	                                         .name = dup_or_null(name), .value = dup_or_null(value) };
	return d->n_targets++;
}

int doc_add_form(doc *d, const char *action, int post)
{
	d->forms = room_for(d->forms, d->n_forms, &d->cap_forms, sizeof(doc_form));
	d->forms[d->n_forms] = (doc_form){ strdup(action), post };
	return d->n_forms++;
}

int doc_add_field(doc *d, int form, const char *name, const char *value, int row, int secret, int width)
{
	d->fields = room_for(d->fields, d->n_fields, &d->cap_fields, sizeof(doc_field));
	d->fields[d->n_fields] = (doc_field){ form, strdup(name), strdup(value), row, secret, width };
	return d->n_fields++;
}

int doc_add_image(doc *d, const char *url, int row, int n_rows)
{
	d->images = room_for(d->images, d->n_images, &d->cap_images, sizeof(doc_image));
	d->images[d->n_images] = (doc_image){ strdup(url), row, n_rows, 0 };
	return d->n_images++;
}

void doc_field_row(doc *d, int field)
{
	const doc_field *fd = &d->fields[field];
	if (fd->row < 0 || fd->row >= d->n)
		return;
	doc_row *r = &d->rows[fd->row];
	const int w = fd->width;
	int n = 0;
	r->b[n++] = WEB_C_FIELD;
	r->b[n++] = (unsigned char)(field >> 8);
	r->b[n++] = (unsigned char)field;
	const size_t len = strlen(fd->value);
	int col = 0;
	for (size_t i = 0; i < len && col < w; i++) {
		const unsigned char c = (unsigned char)fd->value[i];
		if (c < 0x20 || (c >= 0x7f && c < 0xa0))
			continue;
		r->b[n++] = fd->secret ? '*' : c;
		col++;
	}
	while (col < w) {
		r->b[n++] = ' ';
		col++;
	}
	r->b[n++] = WEB_C_END;
	r->len = (unsigned char)n;
}

size_t doc_row_text(const doc_row *r, char *out, size_t cap)
{
	size_t n = 0;
	if (r->len && r->b[0] == WEB_ART_MARK) {
		if (cap)
			out[0] = '\0';
		return 0;
	}
	for (int i = 0; i < r->len && n + 2 < cap; i++) {
		const unsigned char c = r->b[i];
		if (c == WEB_C_LINK || c == WEB_C_FIELD)
			i += 2;
		else if (c >= 0x20)
			out[n++] = (char)c;
	}
	out[n++] = '\n';
	out[n] = '\0';
	return n;
}

/* ---- word wrap ---- */

void flow_init(flow *f, doc *d, int width)
{
	memset(f, 0, sizeof(*f));
	f->d = d;
	f->width = width > WEB_ROW_BYTES - 8 ? WEB_ROW_BYTES - 8 : width;
	f->style = f->line_style = WEB_S_NORMAL;
	f->link = f->line_link = -1;
	f->blank = 1;
}

static void put_byte(flow *f, unsigned char c)
{
	if (f->line_len < WEB_ROW_BYTES)
		f->line[f->line_len++] = c;
}

static void finish_line(flow *f)
{
	if (f->line_link >= 0)
		put_byte(f, WEB_C_END);
	doc_add_row(f->d, f->line, (size_t)f->line_len);
	f->blank = f->col == 0;
	f->line_len = 0;
	f->col = 0;
	f->started = 0;
	f->line_style = WEB_S_NORMAL;
	f->line_link = -1;
}

static void put_indent(flow *f)
{
	for (int i = 0; i < f->indent && f->col < f->width / 2; i++) {
		put_byte(f, ' ');
		f->col++;
	}
}

/* Bring the line up to date with the style and link now wanted. */
static void sync_look(flow *f)
{
	if (f->line_link >= 0 && f->line_link != f->link) {
		put_byte(f, WEB_C_END);
		f->line_link = -1;
	}
	if (f->line_style != f->style) {
		put_byte(f, (unsigned char)f->style);
		f->line_style = f->style;
	}
	if (f->link >= 0 && f->line_link != f->link) {
		put_byte(f, WEB_C_LINK);
		put_byte(f, (unsigned char)(f->link >> 8));
		put_byte(f, (unsigned char)f->link);
		f->line_link = f->link;
	}
}

static void flush_word(flow *f)
{
	if (!f->word_len)
		return;
	const int fits_row = f->line_len + f->word_len + 8 <= WEB_ROW_BYTES;
	if (f->col && (f->col + f->space + f->word_len > f->width || !fits_row))
		finish_line(f);
	if (!f->col && f->indent)
		put_indent(f);
	if (f->line_link >= 0 && f->line_link != f->link) {
		put_byte(f, WEB_C_END);        /* before the space, so the link's underline stops at its last word */
		f->line_link = -1;
	}
	if (f->space && f->started) {
		put_byte(f, ' ');
		f->col++;
	}
	sync_look(f);
	for (int i = 0; i < f->word_len; i++)
		put_byte(f, f->word[i]);
	f->col += f->word_len;
	f->started = 1;
	f->word_len = 0;
	f->space = 0;
}

void flow_codepoint(flow *f, unsigned cp)
{
	if (f->pre && cp == '\n') {
		flush_word(f);
		f->space = 0;
		if (!f->col)
			doc_add_row(f->d, f->line, 0);
		else
			finish_line(f);
		f->blank = 0;
		return;
	}
	if (cp == ' ' || cp == '\t' || cp == '\n' || cp == '\r' || cp == '\f') {
		if (!f->pre) {
			flush_word(f);
			f->space = 1;
			return;
		}
		cp = ' ';
		if (f->col + f->word_len >= f->width)
			flush_word(f);
	}
	if (cp < 0x20 || (cp >= 0x7f && cp < 0xa0))
		return;
	if (f->word_len >= f->width - f->indent || f->word_len >= WEB_ROW_BYTES - 8) {
		flush_word(f);                 /* a word longer than the screen: break it */
		f->space = 0;
	}
	if (f->word_len + f->col >= f->width && f->pre) {
		flush_word(f);
		finish_line(f);
	}
	if (cp == 0xa0)
		cp = ' ';
	f->word[f->word_len++] = (unsigned char)cp;
}

/* Characters beyond Latin-1 as the ASCII people would type for them. Unknown ones (emoji and the like) drop. */
static void flow_wide(flow *f, unsigned cp)
{
	static const struct { unsigned cp; const char *s; } MAP[] = {
		{ 0x2018, "'" }, { 0x2019, "'" }, { 0x201a, "'" }, { 0x201c, "\"" }, { 0x201d, "\"" }, { 0x201e, "\"" },
		{ 0x2010, "-" }, { 0x2011, "-" }, { 0x2012, "-" }, { 0x2013, "-" }, { 0x2014, "--" }, { 0x2015, "--" },
		{ 0x2022, "*" }, { 0x2023, ">" }, { 0x25cf, "*" }, { 0x25aa, "*" }, { 0x2026, "..." }, { 0x2032, "'" },
		{ 0x2033, "\"" }, { 0x2039, "<" }, { 0x203a, ">" }, { 0x2190, "<-" }, { 0x2192, "->" }, { 0x2191, "^" },
		{ 0x2193, "v" }, { 0x2212, "-" }, { 0x2248, "~" }, { 0x2260, "!=" }, { 0x2264, "<=" }, { 0x2265, ">=" },
		{ 0x20ac, "EUR" }, { 0x2122, "(tm)" }, { 0x2713, "v" }, { 0x2717, "x" }, { 0x00ad, "" }, { 0x200b, "" },
		{ 0x202f, " " }, { 0x2009, " " }, { 0x2003, " " }, { 0x2002, " " }, { 0x3000, " " },
	};
	for (size_t i = 0; i < sizeof(MAP) / sizeof(MAP[0]); i++)
		if (MAP[i].cp == cp) {
			for (const char *p = MAP[i].s; *p; p++)
				flow_codepoint(f, (unsigned char)*p);
			return;
		}
}

/* The UTF-8 character at s, or the byte alone as Latin-1 if it isn't valid, which also handles old pages. */
static size_t next_char(const char *s, size_t n, unsigned *cp)
{
	const unsigned char *u = (const unsigned char *)s;
	const unsigned c = u[0];
	int extra = 0;
	unsigned v = c;
	if (c >= 0xf0 && c < 0xf5) {
		extra = 3;
		v = c & 0x07u;
	} else if (c >= 0xe0 && c < 0xf0) {
		extra = 2;
		v = c & 0x0fu;
	} else if (c >= 0xc2 && c < 0xe0) {
		extra = 1;
		v = c & 0x1fu;
	}
	if (!extra || (size_t)extra >= n) {
		*cp = c;
		return 1;
	}
	for (int i = 1; i <= extra; i++) {
		if ((u[i] & 0xc0u) != 0x80u) {
			*cp = c;
			return 1;
		}
		v = v << 6 | (u[i] & 0x3fu);
	}
	*cp = v;
	return (size_t)extra + 1;
}

static void flow_any(flow *f, unsigned cp)
{
	if (cp < 0x100 && cp != 0xad)
		flow_codepoint(f, cp);
	else
		flow_wide(f, cp);
}

void flow_text(flow *f, const char *s, size_t n)
{
	size_t i = 0;
	while (i < n) {
		unsigned cp;
		i += next_char(s + i, n - i, &cp);
		flow_any(f, cp);
	}
}

void flow_style(flow *f, int style)
{
	if (style == f->style)
		return;
	flush_word(f);
	f->style = style;
}

void flow_link(flow *f, int target)
{
	if (target == f->link)
		return;
	flush_word(f);
	f->link = target;
}

void flow_break(flow *f)
{
	flush_word(f);
	f->space = 0;
	if (f->col)
		finish_line(f);
}

void flow_blank(flow *f)
{
	flow_break(f);
	if (!f->blank) {
		doc_add_row(f->d, f->line, 0);
		f->blank = 1;
	}
}

void flow_indent(flow *f, int cells)
{
	flush_word(f);
	f->indent = cells < 0 ? 0 : cells;
}

void flow_end(flow *f)
{
	flow_break(f);
}

/* ---- Markdown, as much as a chat reply needs ---- */

static size_t find_from(const char *s, size_t n, size_t from, const char *what)
{
	const size_t len = strlen(what);
	for (size_t i = from; i + len <= n; i++)
		if (!memcmp(s + i, what, len))
			return i;
	return n;
}

static int is_url_end(char c)
{
	return c == ' ' || c == '\t' || c == '\n' || c == ')' || c == ']' || c == '>' || c == '"' || c == '\'' || c == '`';
}

static void put_link(flow *f, const char *label, size_t label_n, const char *url, size_t url_n)
{
	char *copy = strndup(url, url_n);
	if (!copy)
		abort();
	const int saved = f->style;
	flow_link(f, doc_add_link(f->d, copy));
	flow_text(f, label, label_n);
	flow_link(f, -1);
	flow_style(f, saved);
	free(copy);
}

static void inline_markdown(flow *f, const char *s, size_t n, int base_style)
{
	size_t i = 0;
	while (i < n) {
		if (s[i] == '*' && i + 1 < n && s[i + 1] == '*') {
			const size_t end = find_from(s, n, i + 2, "**");
			if (end < n) {
				flow_style(f, WEB_S_BOLD);
				flow_text(f, s + i + 2, end - i - 2);
				flow_style(f, base_style);
				i = end + 2;
				continue;
			}
		}
		if (s[i] == '`') {
			const size_t end = find_from(s, n, i + 1, "`");
			if (end < n) {
				flow_style(f, WEB_S_DIM);
				flow_text(f, s + i + 1, end - i - 1);
				flow_style(f, base_style);
				i = end + 1;
				continue;
			}
		}
		if (s[i] == '[') {
			const size_t mid = find_from(s, n, i + 1, "](");
			const size_t end = mid < n ? find_from(s, n, mid + 2, ")") : n;
			if (end < n && (!strncmp(s + mid + 2, "http://", 7) || !strncmp(s + mid + 2, "https://", 8))) {
				put_link(f, s + i + 1, mid - i - 1, s + mid + 2, end - mid - 2);
				i = end + 1;
				continue;
			}
		}
		if ((n - i > 8 && !strncmp(s + i, "http://", 7)) || (n - i > 9 && !strncmp(s + i, "https://", 8))) {
			size_t end = i;
			while (end < n && !is_url_end(s[end]))
				end++;
			while (end > i && (s[end - 1] == '.' || s[end - 1] == ',' || s[end - 1] == ';' || s[end - 1] == ':'))
				end--;
			put_link(f, s + i, end - i, s + i, end - i);
			i = end;
			continue;
		}
		unsigned cp;
		i += next_char(s + i, n - i, &cp);
		flow_any(f, cp);
	}
}

void doc_markdown(flow *f, const char *s, size_t n)
{
	size_t i = 0;
	int code = 0;
	while (i < n) {
		const char *nl = memchr(s + i, '\n', n - i);
		const size_t end = nl ? (size_t)(nl - s) : n;
		const char *line = s + i;
		size_t len = end - i;
		i = end + 1;
		if (len >= 3 && !memcmp(line, "```", 3)) {
			flow_break(f);
			code = !code;
			f->pre = code;
			flow_style(f, code ? WEB_S_DIM : WEB_S_NORMAL);
			continue;
		}
		if (code) {
			flow_text(f, line, len);
			flow_codepoint(f, '\n');
			continue;
		}
		size_t start = 0;
		while (start < len && line[start] == ' ')
			start++;
		if (start == len) {
			flow_blank(f);
			continue;
		}
		line += start;
		len -= start;
		flow_break(f);
		if (line[0] == '#') {
			size_t hashes = 0;
			while (hashes < len && line[hashes] == '#')
				hashes++;
			if (hashes < len && line[hashes] == ' ') {
				flow_style(f, WEB_S_HEAD);
				inline_markdown(f, line + hashes + 1, len - hashes - 1, WEB_S_HEAD);
				flow_break(f);
				flow_style(f, WEB_S_NORMAL);
				continue;
			}
		}
		if (len >= 2 && (line[0] == '-' || line[0] == '*') && line[1] == ' ') {
			flow_text(f, "* ", 2);
			flow_indent(f, 2);
			f->space = 1;
			inline_markdown(f, line + 2, len - 2, WEB_S_NORMAL);
			flow_break(f);
			flow_indent(f, 0);
			continue;
		}
		if (line[0] == '>') {
			flow_style(f, WEB_S_DIM);
			flow_indent(f, 2);
			inline_markdown(f, line + 1, len - 1, WEB_S_DIM);
			flow_break(f);
			flow_indent(f, 0);
			flow_style(f, WEB_S_NORMAL);
			continue;
		}
		inline_markdown(f, line, len, WEB_S_NORMAL);
		flow_break(f);
	}
	flow_break(f);
	f->pre = 0;
	flow_style(f, WEB_S_NORMAL);
}
