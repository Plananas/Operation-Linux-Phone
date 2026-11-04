#define _GNU_SOURCE
#include "html.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "url.h"

enum { ATTR_MAX = 4096, NAME_MAX_LEN = 16, ART_PER_ROW = 2, IMG_ROWS_DEFAULT = 12, IMG_ROWS_MAX = 20, IMG_ROWS_MIN = 3, ICON_PX = 40 };

typedef struct {
	const char *name;
	unsigned cp;
} entity;

static const entity ENTITIES[] = {
	{ "amp", '&' }, { "lt", '<' }, { "gt", '>' }, { "quot", '"' }, { "apos", '\'' }, { "nbsp", 0xa0 }, { "copy", 0xa9 },
	{ "reg", 0xae }, { "mdash", 0x2014 }, { "ndash", 0x2013 }, { "hellip", 0x2026 }, { "lsquo", 0x2018 },
	{ "rsquo", 0x2019 }, { "ldquo", 0x201c }, { "rdquo", 0x201d }, { "bull", 0x2022 }, { "middot", 0xb7 },
	{ "laquo", 0xab }, { "raquo", 0xbb }, { "times", 0xd7 }, { "euro", 0x20ac }, { "pound", 0xa3 }, { "trade", 0x2122 },
	{ "rarr", 0x2192 }, { "larr", 0x2190 }, { "deg", 0xb0 }, { "eacute", 0xe9 }, { "egrave", 0xe8 }, { "agrave", 0xe0 },
	{ "uuml", 0xfc }, { "ouml", 0xf6 }, { "auml", 0xe4 }, { "shy", 0xad }, { "sect", 0xa7 }, { "para", 0xb6 },
};

/* The entity at s (which starts with &). Returns the characters used, or 0 if it isn't one. */
static size_t read_entity(const char *s, size_t n, unsigned *cp)
{
	size_t i = 1;
	if (i < n && s[i] == '#') {
		i++;
		const int hex = i < n && (s[i] == 'x' || s[i] == 'X');
		i += (size_t)hex;
		unsigned long v = 0;
		const size_t digits = i;
		while (i < n && i - digits < 8 && (hex ? isxdigit((unsigned char)s[i]) : isdigit((unsigned char)s[i]))) {
			const char c = s[i++];
			v = v * (hex ? 16u : 10u) + (unsigned long)(isdigit((unsigned char)c) ? c - '0' : (tolower((unsigned char)c) - 'a' + 10));
		}
		if (i == digits)
			return 0;
		*cp = (unsigned)v;
		return i + (i < n && s[i] == ';');
	}
	while (i < n && i < 12 && isalnum((unsigned char)s[i]))
		i++;
	for (size_t e = 0; e < sizeof(ENTITIES) / sizeof(ENTITIES[0]); e++)
		if (strlen(ENTITIES[e].name) == i - 1 && !strncmp(s + 1, ENTITIES[e].name, i - 1)) {
			*cp = ENTITIES[e].cp;
			return i + (i < n && s[i] == ';');
		}
	return 0;
}

static size_t put_utf8(unsigned cp, char *out)
{
	if (cp < 0x80) {
		out[0] = (char)cp;
		return 1;
	}
	if (cp < 0x800) {
		out[0] = (char)(0xc0 | cp >> 6);
		out[1] = (char)(0x80 | (cp & 0x3f));
		return 2;
	}
	if (cp < 0x10000) {
		out[0] = (char)(0xe0 | cp >> 12);
		out[1] = (char)(0x80 | (cp >> 6 & 0x3f));
		out[2] = (char)(0x80 | (cp & 0x3f));
		return 3;
	}
	if (cp > 0x10ffff)
		return 0;
	out[0] = (char)(0xf0 | cp >> 18);
	out[1] = (char)(0x80 | (cp >> 12 & 0x3f));
	out[2] = (char)(0x80 | (cp >> 6 & 0x3f));
	out[3] = (char)(0x80 | (cp & 0x3f));
	return 4;
}

/* src with its entities decoded, as UTF-8. */
static void decode_to(const char *src, size_t n, char *out, size_t cap)
{
	size_t o = 0;
	for (size_t i = 0; i < n && o + 5 < cap;) {
		unsigned cp;
		size_t used;
		if (src[i] == '&' && (used = read_entity(src + i, n - i, &cp))) {
			o += put_utf8(cp, out + o);
			i += used;
		} else {
			out[o++] = src[i++];
		}
	}
	if (cap)
		out[o] = '\0';
}

int html_attr(const char *tag, size_t n, const char *name, char *out, size_t cap)
{
	const size_t name_n = strlen(name);
	size_t i = 0;
	while (i < n && !isspace((unsigned char)tag[i]) && tag[i] != '/')     /* the tag's own name */
		i++;
	while (i < n) {
		while (i < n && (isspace((unsigned char)tag[i]) || tag[i] == '/'))
			i++;
		const size_t start = i;
		while (i < n && !isspace((unsigned char)tag[i]) && tag[i] != '=' && tag[i] != '/')
			i++;
		const size_t len = i - start;
		while (i < n && isspace((unsigned char)tag[i]))
			i++;
		const char *value = "";
		size_t value_n = 0;
		if (i < n && tag[i] == '=') {
			i++;
			while (i < n && isspace((unsigned char)tag[i]))
				i++;
			if (i < n && (tag[i] == '"' || tag[i] == '\'')) {
				const char quote = tag[i++];
				value = tag + i;
				while (i < n && tag[i] != quote)
					i++;
				value_n = (size_t)(tag + i - value);
				i += i < n;
			} else {
				value = tag + i;
				while (i < n && !isspace((unsigned char)tag[i]))
					i++;
				value_n = (size_t)(tag + i - value);
			}
		}
		if (len == name_n && !strncasecmp(tag + start, name, len)) {
			decode_to(value, value_n, out, cap);
			return 1;
		}
		if (!len)
			i++;
	}
	return 0;
}

/* ---- the walk ---- */

typedef struct {
	const char *html;
	size_t n;
	char base[4096];
	html_options opt;
	flow f;
	doc *d;
	int bold, head, dim, list_depth;
	int ol_count[8];
	int current_form;
	int in_title, in_button, in_textarea;
	const char *link_url_for_inline;
	char inline_url[4096];
} walker;

static int name_in(const char *name, const char *const *list)
{
	for (; *list; list++)
		if (!strcmp(name, *list))
			return 1;
	return 0;
}

static const char *const VOID_TAGS[] = { "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                                         "param", "source", "track", "wbr", NULL };
static const char *const SKIPPED[] = { "script", "style", "svg", "template", "iframe", "object", "embed", "canvas",
                                       "audio", "video", "map", "math", "dialog", "datalist", "head-skip", NULL };
static const char *const MENUS[] = { "nav", "aside", NULL };
static const char *const BLOCKS[] = { "div", "ul", "ol", "dl", "table", "tr", "section", "article", "header", "footer",
                                      "main", "form", "figure", "figcaption", "address", "center", "fieldset",
                                      "details", "summary", "dt", "dd", "body", "caption", "label-block", NULL };
static const char *const BLANKS[] = { "p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr", NULL };

static void apply_style(walker *w)
{
	flow_style(&w->f, w->head ? WEB_S_HEAD : w->bold ? WEB_S_BOLD : w->dim ? WEB_S_DIM : WEB_S_NORMAL);
}

static void text_run(walker *w, const char *s, size_t n)
{
	size_t i = 0;
	while (i < n) {
		const char *amp = memchr(s + i, '&', n - i);
		const size_t plain = amp ? (size_t)(amp - s) - i : n - i;
		flow_text(&w->f, s + i, plain);
		i += plain;
		if (i < n) {
			unsigned cp;
			const size_t used = read_entity(s + i, n - i, &cp);
			if (used) {
				char u[4];
				flow_text(&w->f, u, put_utf8(cp, u));
				i += used;
			} else {
				flow_text(&w->f, "&", 1);
				i++;
			}
		}
	}
}

/* The end of the tag that starts just after a <, allowing for > inside quotes. */
static size_t tag_end(const char *s, size_t n, size_t i)
{
	char quote = 0;
	for (; i < n; i++) {
		if (quote) {
			if (s[i] == quote)
				quote = 0;
		} else if (s[i] == '"' || s[i] == '\'') {
			quote = s[i];
		} else if (s[i] == '>') {
			return i;
		}
	}
	return n;
}

/* Where the matching </name> ends, counting nested ones. Raw tags have no nesting and no markup inside. */
static size_t skip_element(const char *s, size_t n, size_t i, const char *name, int raw)
{
	const size_t len = strlen(name);
	int depth = 1;
	while (i < n) {
		const char *lt = memchr(s + i, '<', n - i);
		if (!lt)
			return n;
		i = (size_t)(lt - s) + 1;
		const int closing = i < n && s[i] == '/';
		const size_t at = i + (size_t)closing;
		if (at + len > n || strncasecmp(s + at, name, len) || isalnum((unsigned char)s[at + len < n ? at + len : n - 1]))
			continue;
		if (raw && !closing)
			continue;
		depth += closing ? -1 : 1;
		const size_t end = tag_end(s, n, at);
		if (!depth)
			return end < n ? end + 1 : n;
		i = end;
	}
	return n;
}

static int hidden_by_attrs(const char *tag, size_t n)
{
	char v[256];
	if (html_attr(tag, n, "hidden", v, sizeof(v)))
		return 1;
	if (html_attr(tag, n, "aria-hidden", v, sizeof(v)) && !strcmp(v, "true"))
		return 1;
	if (html_attr(tag, n, "style", v, sizeof(v))) {
		char *squeezed = v;
		for (char *r = v; *r; r++)
			if (!isspace((unsigned char)*r))
				*squeezed++ = (char)tolower((unsigned char)*r);
		*squeezed = '\0';
		if (strstr(v, "display:none") || strstr(v, "visibility:hidden"))
			return 1;
	}
	return 0;
}

static void start_link(walker *w, const char *tag, size_t n)
{
	char href[ATTR_MAX], url[ATTR_MAX];
	if (!html_attr(tag, n, "href", href, sizeof(href)) || href[0] == '#')
		return;
	if (!url_resolve(w->base, href, url, sizeof(url)))
		return;
	flow_link(&w->f, doc_add_link(w->d, url));
	if (w->opt.inline_urls)
		snprintf(w->inline_url, sizeof(w->inline_url), "%s", url);
}

static void end_link(walker *w)
{
	flow_link(&w->f, -1);
	apply_style(w);
	if (w->inline_url[0]) {
		flow_text(&w->f, " <", 2);
		flow_text(&w->f, w->inline_url, strlen(w->inline_url));
		flow_text(&w->f, ">", 1);
		w->inline_url[0] = '\0';
	}
}

/* A number from an attribute, ignoring what can't be used (a width of 100%, say). */
static int attr_px(const char *tag, size_t n, const char *name)
{
	char v[32];
	if (!html_attr(tag, n, name, v, sizeof(v)) || strchr(v, '%'))
		return 0;
	return atoi(v);
}

static void add_image(walker *w, const char *tag, size_t n)
{
	char src[ATTR_MAX], url[ATTR_MAX], alt[256] = "";
	const int px_w = attr_px(tag, n, "width"), px_h = attr_px(tag, n, "height");
	if ((px_w && px_w < ICON_PX) || (px_h && px_h < ICON_PX))
		return;
	const int has_src = html_attr(tag, n, "src", src, sizeof(src));
	if ((!has_src || !strncmp(src, "data:", 5)) && !html_attr(tag, n, "data-src", src, sizeof(src)))
		return;
	html_attr(tag, n, "alt", alt, sizeof(alt));
	if (w->opt.inline_urls) {
		if (alt[0]) {
			flow_text(&w->f, " [image: ", 9);
			flow_text(&w->f, alt, strlen(alt));
			flow_text(&w->f, "] ", 2);
		}
		return;
	}
	if (!url_resolve(w->base, src, url, sizeof(url)))
		return;
	/* Reserve its rows now, so nothing moves when it arrives. The art's cells are 8 x 12. Pictures past the
	 * number that get fetched only need a line to say they're there. */
	int rows = IMG_ROWS_DEFAULT;
	if (w->d->n_images >= HTML_IMAGES_MAX)
		rows = 1;
	else if (px_w && px_h) {
		rows = (WEB_ART_COLS * 2 * px_h / (3 * px_w) + ART_PER_ROW - 1) / ART_PER_ROW;
		rows = rows < IMG_ROWS_MIN ? IMG_ROWS_MIN : rows > IMG_ROWS_MAX ? IMG_ROWS_MAX : rows;
	}
	flow_blank(&w->f);
	const int first = w->d->n;
	const int saved_link = w->f.link;
	flow_link(&w->f, -1);
	flow_style(&w->f, WEB_S_DIM);
	flow_text(&w->f, "[image", 6);
	if (alt[0]) {
		flow_text(&w->f, ": ", 2);
		flow_text(&w->f, alt, strlen(alt) > 36 ? 36 : strlen(alt));
	}
	flow_text(&w->f, "]", 1);
	flow_break(&w->f);
	apply_style(w);
	flow_link(&w->f, saved_link);
	const int used = w->d->n - first;
	for (int i = used; i < rows; i++)
		doc_add_row(w->d, (const unsigned char *)"", 0);
	if (w->d->n > first && rows > 1)
		doc_add_image(w->d, url, first, w->d->n - first);
	w->f.blank = 1;
}

static void add_field_row(walker *w, const char *name, const char *value, int secret)
{
	flow_break(&w->f);
	const int row = w->d->n;
	doc_add_row(w->d, (const unsigned char *)"", 0);
	if (w->d->n == row)
		return;
	const int width = w->f.width - 2 < 8 ? 8 : w->f.width - 2;
	doc_field_row(w->d, doc_add_field(w->d, w->current_form, name, value, row, secret, width));
	w->f.blank = 0;
}

static void add_button(walker *w, const char *label, const char *name, const char *value)
{
	const int saved = w->f.link;
	if (w->current_form >= 0)
		flow_link(&w->f, doc_add_submit(w->d, w->current_form, name, value));
	flow_text(&w->f, "[", 1);
	flow_text(&w->f, label, strlen(label));
	flow_text(&w->f, "]", 1);
	flow_link(&w->f, saved);
	apply_style(w);
	w->f.space = 1;
}

static void add_input(walker *w, const char *tag, size_t n)
{
	char type[32] = "text", name[256] = "", value[ATTR_MAX] = "";
	html_attr(tag, n, "type", type, sizeof(type));
	html_attr(tag, n, "name", name, sizeof(name));
	html_attr(tag, n, "value", value, sizeof(value));
	for (char *c = type; *c; c++)
		*c = (char)tolower((unsigned char)*c);
	if (w->opt.inline_urls)
		return;
	if (!strcmp(type, "hidden")) {
		if (w->current_form >= 0 && name[0])
			doc_add_field(w->d, w->current_form, name, value, -1, 0, 0);
	} else if (!strcmp(type, "submit") || !strcmp(type, "button") || !strcmp(type, "image")) {
		add_button(w, value[0] ? value : "go", name[0] ? name : NULL, name[0] ? value : NULL);
	} else if (!strcmp(type, "checkbox") || !strcmp(type, "radio")) {
		char checked[8];
		if (html_attr(tag, n, "checked", checked, sizeof(checked)) && w->current_form >= 0 && name[0])
			doc_add_field(w->d, w->current_form, name, value[0] ? value : "on", -1, 0, 0);
	} else if (strcmp(type, "file") && strcmp(type, "reset") && w->current_form >= 0 && name[0]) {
		add_field_row(w, name, value, !strcmp(type, "password"));
	}
}

/* <select> can't be changed here: show the choice that will be sent. */
static size_t add_select(walker *w, const char *tag, size_t n, size_t after)
{
	char name[256] = "", first[ATTR_MAX] = "", chosen[ATTR_MAX] = "";
	const size_t end = skip_element(w->html, w->n, after, "select", 1);
	html_attr(tag, n, "name", name, sizeof(name));
	for (size_t i = after; i < end;) {
		const char *lt = memchr(w->html + i, '<', end - i);
		if (!lt)
			break;
		i = (size_t)(lt - w->html) + 1;
		const size_t close = tag_end(w->html, end, i);
		if (close - i > 6 && !strncasecmp(w->html + i, "option", 6)) {
			char v[ATTR_MAX], flag[8];
			if (html_attr(w->html + i, close - i, "value", v, sizeof(v))) {
				if (!first[0])
					snprintf(first, sizeof(first), "%s", v);
				if (html_attr(w->html + i, close - i, "selected", flag, sizeof(flag)))
					snprintf(chosen, sizeof(chosen), "%s", v);
			}
		}
		i = close;
	}
	if (w->current_form >= 0 && name[0] && !w->opt.inline_urls)
		doc_add_field(w->d, w->current_form, name, chosen[0] ? chosen : first, -1, 0, 0);
	return end;
}

static void open_form(walker *w, const char *tag, size_t n)
{
	char action[ATTR_MAX] = "", method[16] = "", url[ATTR_MAX];
	html_attr(tag, n, "action", action, sizeof(action));
	html_attr(tag, n, "method", method, sizeof(method));
	if (w->opt.inline_urls || !url_resolve(w->base, action, url, sizeof(url))) {
		w->current_form = -1;
		return;
	}
	w->current_form = doc_add_form(w->d, url, !strcasecmp(method, "post"));
}

static void list_item(walker *w)
{
	flow_break(&w->f);
	const int depth = w->list_depth > 8 ? 8 : w->list_depth;
	flow_indent(&w->f, depth > 1 ? (depth - 1) * 2 : 0);
	char mark[16] = "* ";
	if (depth >= 1 && w->ol_count[depth - 1] > 0)
		snprintf(mark, sizeof(mark), "%d. ", w->ol_count[depth - 1]++);
	flow_text(&w->f, mark, strlen(mark));
	w->f.space = 1;
	flow_indent(&w->f, depth * 2);
}

static void open_tag(walker *w, const char *name, const char *tag, size_t n)
{
	if (name_in(name, BLANKS))
		flow_blank(&w->f);
	else if (name_in(name, BLOCKS))
		flow_break(&w->f);

	if (name[0] == 'h' && name[1] >= '1' && name[1] <= '6' && !name[2]) {
		w->head++;
		apply_style(w);
	} else if (!strcmp(name, "b") || !strcmp(name, "strong")) {
		w->bold++;
		apply_style(w);
	} else if (!strcmp(name, "code") || !strcmp(name, "tt") || !strcmp(name, "kbd") || !strcmp(name, "small")) {
		w->dim++;
		apply_style(w);
	} else if (!strcmp(name, "pre")) {
		w->dim++;
		apply_style(w);
		w->f.pre = 1;
	} else if (!strcmp(name, "blockquote")) {
		w->dim++;
		apply_style(w);
		flow_indent(&w->f, w->f.indent + 2);
	} else if (!strcmp(name, "br")) {
		flow_break(&w->f);
	} else if (!strcmp(name, "hr")) {
		flow_style(&w->f, WEB_S_DIM);
		for (int i = 0; i < w->f.width; i++)
			flow_text(&w->f, "-", 1);
		apply_style(w);
		flow_blank(&w->f);
	} else if (!strcmp(name, "a")) {
		start_link(w, tag, n);
	} else if (!strcmp(name, "img")) {
		add_image(w, tag, n);
	} else if (!strcmp(name, "ul") || !strcmp(name, "ol")) {
		if (w->list_depth < 8)
			w->ol_count[w->list_depth] = name[0] == 'o' ? 1 : 0;
		w->list_depth++;
	} else if (!strcmp(name, "li")) {
		list_item(w);
	} else if (!strcmp(name, "td") || !strcmp(name, "th")) {
		w->f.space = 1;
	} else if (!strcmp(name, "form")) {
		open_form(w, tag, n);
	} else if (!strcmp(name, "input")) {
		add_input(w, tag, n);
	} else if (!strcmp(name, "base")) {
		char href[ATTR_MAX], url[ATTR_MAX];
		if (html_attr(tag, n, "href", href, sizeof(href)) && url_resolve(w->base, href, url, sizeof(url)))
			snprintf(w->base, sizeof(w->base), "%s", url);
	} else if (!strcmp(name, "meta")) {
		char http[32], content[ATTR_MAX];
		if (html_attr(tag, n, "http-equiv", http, sizeof(http)) && !strcasecmp(http, "refresh") &&
		    html_attr(tag, n, "content", content, sizeof(content)) && atoi(content) <= 5) {
			const char *eq = strcasestr(content, "url=");
			char url[ATTR_MAX];
			if (eq && url_resolve(w->base, eq + 4, url, sizeof(url)) && !w->d->refresh)
				w->d->refresh = strdup(url);
		}
	}
}

static void close_tag(walker *w, const char *name)
{
	if (name[0] == 'h' && name[1] >= '1' && name[1] <= '6' && !name[2]) {
		w->head = w->head > 0 ? w->head - 1 : 0;
		flow_break(&w->f);
		apply_style(w);
		flow_blank(&w->f);
		return;
	}
	if (!strcmp(name, "b") || !strcmp(name, "strong")) {
		w->bold = w->bold > 0 ? w->bold - 1 : 0;
		apply_style(w);
	} else if (!strcmp(name, "code") || !strcmp(name, "tt") || !strcmp(name, "kbd") || !strcmp(name, "small")) {
		w->dim = w->dim > 0 ? w->dim - 1 : 0;
		apply_style(w);
	} else if (!strcmp(name, "pre")) {
		flow_break(&w->f);
		w->f.pre = 0;
		w->dim = w->dim > 0 ? w->dim - 1 : 0;
		apply_style(w);
		flow_blank(&w->f);
	} else if (!strcmp(name, "blockquote")) {
		flow_break(&w->f);
		flow_indent(&w->f, w->f.indent - 2);
		w->dim = w->dim > 0 ? w->dim - 1 : 0;
		apply_style(w);
		flow_blank(&w->f);
	} else if (!strcmp(name, "a")) {
		end_link(w);
	} else if (!strcmp(name, "ul") || !strcmp(name, "ol")) {
		flow_break(&w->f);
		w->list_depth = w->list_depth > 0 ? w->list_depth - 1 : 0;
		const int depth = w->list_depth > 8 ? 8 : w->list_depth;
		flow_indent(&w->f, depth * 2);
	} else if (!strcmp(name, "li")) {
		flow_break(&w->f);
	} else if (!strcmp(name, "form")) {
		flow_break(&w->f);
		w->current_form = -1;
	} else if (!strcmp(name, "p")) {
		flow_blank(&w->f);
	} else if (name_in(name, BLOCKS)) {
		flow_break(&w->f);
	}
}

void html_layout(const char *html, size_t n, const char *base_url, html_options opt, doc *out)
{
	walker *w = calloc(1, sizeof(*w));
	if (!w)
		abort();
	w->html = html;
	w->n = n;
	w->opt = opt;
	w->d = out;
	w->current_form = -1;
	snprintf(w->base, sizeof(w->base), "%s", base_url);
	flow_init(&w->f, out, opt.width);
	size_t i = 0;
	while (i < n) {
		const char *lt = memchr(html + i, '<', n - i);
		const size_t text_end = lt ? (size_t)(lt - html) : n;
		text_run(w, html + i, text_end - i);
		if (!lt)
			break;
		i = text_end + 1;
		if (i >= n)
			break;
		if (!strncmp(html + i, "!--", n - i < 3 ? n - i : 3)) {
			const char *close = NULL;
			for (size_t k = i + 3; k + 3 <= n; k++)
				if (!memcmp(html + k, "-->", 3)) {
					close = html + k;
					break;
				}
			i = close ? (size_t)(close - html) + 3 : n;
			continue;
		}
		if (html[i] == '!' || html[i] == '?') {
			const size_t end = tag_end(html, n, i);
			i = end < n ? end + 1 : n;
			continue;
		}
		const int closing = html[i] == '/';
		const size_t name_at = i + (size_t)closing;
		if (name_at >= n || !isalpha((unsigned char)html[name_at])) {
			flow_text(&w->f, "<", 1);
			continue;
		}
		char name[NAME_MAX_LEN] = "";
		size_t k = 0;
		while (name_at + k < n && (isalnum((unsigned char)html[name_at + k]) || html[name_at + k] == '-') && k + 1 < sizeof(name)) {
			name[k] = (char)tolower((unsigned char)html[name_at + k]);
			k++;
		}
		name[k] = '\0';
		const size_t end = tag_end(html, n, name_at);
		const char *tag = html + name_at;
		const size_t tag_n = end - name_at;
		const size_t after = end < n ? end + 1 : n;
		const int self_closed = tag_n && tag[tag_n - 1] == '/';
		if (closing) {
			close_tag(w, name);
			i = after;
			continue;
		}
		if (!strcmp(name, "title")) {
			const size_t stop = skip_element(html, n, after, "title", 1);
			if (!out->title) {
				char *copy = malloc(1024);
				if (!copy)
					abort();
				size_t len = stop > after ? stop - after : 0;
				const char *close_at = memchr(html + after, '<', len);
				if (close_at)
					len = (size_t)(close_at - (html + after));
				decode_to(html + after, len, copy, 1024);
				out->title = copy;
			}
			i = stop;
			continue;
		}
		const int raw = !strcmp(name, "script") || !strcmp(name, "style") || !strcmp(name, "textarea");
		if (name_in(name, SKIPPED) || (!opt.keep_nav && name_in(name, MENUS)) ||
		    (strcmp(name, "input") && hidden_by_attrs(tag, tag_n))) {
			i = self_closed || name_in(name, VOID_TAGS) ? after : skip_element(html, n, after, name, raw);
			continue;
		}
		if (!strcmp(name, "select")) {
			i = add_select(w, tag, tag_n, after);
			continue;
		}
		if (!strcmp(name, "textarea")) {
			char field[256] = "";
			const size_t stop = skip_element(html, n, after, "textarea", 1);
			html_attr(tag, tag_n, "name", field, sizeof(field));
			if (w->current_form >= 0 && field[0] && !opt.inline_urls) {
				char value[ATTR_MAX];
				size_t len = stop > after ? stop - after : 0;
				const char *close_at = memchr(html + after, '<', len);
				if (close_at)
					len = (size_t)(close_at - (html + after));
				decode_to(html + after, len, value, sizeof(value));
				add_field_row(w, field, value, 0);
			}
			i = stop;
			continue;
		}
		if (!strcmp(name, "button")) {
			/* Its contents are the label. */
			const size_t stop = skip_element(html, n, after, "button", 0);
			char label[128] = "", bname[256] = "", bvalue[ATTR_MAX] = "", type[16] = "submit";
			size_t o = 0;
			int in_tag = 0;
			for (size_t c = after; c < stop && o + 1 < sizeof(label); c++) {
				if (html[c] == '<')
					in_tag = 1;
				else if (html[c] == '>')
					in_tag = 0;
				else if (!in_tag && !(isspace((unsigned char)html[c]) && (!o || label[o - 1] == ' ')))
					label[o++] = isspace((unsigned char)html[c]) ? ' ' : html[c];
			}
			while (o && label[o - 1] == ' ')
				o--;
			label[o] = '\0';
			html_attr(tag, tag_n, "type", type, sizeof(type));
			html_attr(tag, tag_n, "name", bname, sizeof(bname));
			html_attr(tag, tag_n, "value", bvalue, sizeof(bvalue));
			if (w->current_form >= 0 && !strcasecmp(type, "submit") && !opt.inline_urls)
				add_button(w, label[0] ? label : "go", bname[0] ? bname : NULL, bname[0] ? bvalue : NULL);
			i = stop;
			continue;
		}
		open_tag(w, name, tag, tag_n);
		i = after;
	}
	flow_end(&w->f);
	free(w);
}
