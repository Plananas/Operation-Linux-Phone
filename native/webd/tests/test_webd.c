/* Unit tests for webd's pure parts. Run with: make test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ascii.h"
#include "doc.h"
#include "gemini.h"
#include "html.h"
#include "json.h"
#include "url.h"

static int checks, failures;

#define CHECK(cond) do { \
	checks++; \
	if (!(cond)) { \
		failures++; \
		printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
	} \
} while (0)

static int resolves(const char *base, const char *ref, const char *want)
{
	char out[4096];
	const int ok = url_resolve(base, ref, out, sizeof(out));
	if (!want)
		return !ok;
	if (!ok || strcmp(out, want)) {
		printf("  resolve %s + %s = %s (want %s)\n", base, ref, ok ? out : "(failed)", want);
		return 0;
	}
	return 1;
}

static void test_url(void)
{
	url_parts u;
	CHECK(url_parse("https://Example.COM/a?b=1#frag", &u));
	CHECK(u.secure && u.port == 443 && !strcmp(u.host, "example.com") && !strcmp(u.path, "/a?b=1"));
	CHECK(url_parse("http://x:8080", &u) && u.port == 8080 && !strcmp(u.path, "/"));
	CHECK(url_parse("http://[::1]:81/p", &u) && u.port == 81 && !strcmp(u.host, "::1"));
	CHECK(!url_parse("ftp://x/", &u));
	CHECK(!url_parse("https://user:pw@evil.com/", &u));
	CHECK(!url_parse("http://x:99999/", &u));
	CHECK(!url_parse("http://a b/", &u));
	CHECK(!url_parse("http://x/a b", &u));
	CHECK(!url_parse("http://x/a\r\nHost: evil", &u));

	const char *b = "https://a.org/x/y/z.html?q=1";
	CHECK(resolves(b, "w.html", "https://a.org/x/y/w.html"));
	CHECK(resolves(b, "../w", "https://a.org/x/w"));
	CHECK(resolves(b, "../../../../w", "https://a.org/w"));
	CHECK(resolves(b, "./", "https://a.org/x/y/"));
	CHECK(resolves(b, "/r", "https://a.org/r"));
	CHECK(resolves(b, "?p=2", "https://a.org/x/y/z.html?p=2"));
	CHECK(resolves(b, "//c.net/d", "https://c.net/d"));
	CHECK(resolves(b, "http://d.net/", "http://d.net/"));
	CHECK(resolves(b, " a b ", "https://a.org/x/y/a%20b"));
	CHECK(resolves(b, "#top", "https://a.org/x/y/z.html?q=1"));
	CHECK(resolves("http://h:81/a", "b", "http://h:81/b"));
	CHECK(resolves(b, "javascript:alert(1)", NULL));
	CHECK(resolves(b, "file:///etc/passwd", NULL));
	CHECK(resolves(b, "data:text/html,hi", NULL));
	CHECK(resolves(b, "x\r\ny", "https://a.org/x/y/xy"));

	char out[64];
	CHECK(url_from_typed("example.com/a", out, sizeof(out)) && !strcmp(out, "https://example.com/a"));
	CHECK(url_from_typed("http://example.com", out, sizeof(out)) && !strcmp(out, "http://example.com"));
	CHECK(!url_from_typed("file:///etc/passwd", out, sizeof(out)));
	CHECK(url_encode("a b&c", 1, out, sizeof(out)) && !strcmp(out, "a+b%26c"));
	CHECK(url_encode("a b", 0, out, sizeof(out)) && !strcmp(out, "a%20b"));
	CHECK(!url_encode("too long for this", 0, out, 4));
}

/* The doc's rows as plain text. */
static void text_of(const doc *d, char *out, size_t cap)
{
	size_t n = 0;
	out[0] = '\0';
	for (int i = 0; i < d->n; i++) {
		char line[WEB_ROW_BYTES + 8];
		const size_t len = doc_row_text(&d->rows[i], line, sizeof(line));
		if (n + len + 1 < cap) {
			memcpy(out + n, line, len + 1);
			n += len;
		}
	}
}

static void layout(const char *html, doc *d, char *text, size_t cap)
{
	doc_init(d);
	html_layout(html, strlen(html), "https://a.org/dir/page", (html_options){ .width = WEB_COLS }, d);
	text_of(d, text, cap);
}

static int rows_stay_in_width(const doc *d, int width)
{
	for (int i = 0; i < d->n; i++) {
		char line[WEB_ROW_BYTES + 8];
		const size_t len = doc_row_text(&d->rows[i], line, sizeof(line));
		if (len > (size_t)width + 1)
			return 0;
	}
	return 1;
}

static void test_html(void)
{
	static char text[65536];
	doc d;

	layout("<title>The &amp; title</title><h1>Head</h1><p>one <b>two</b>  three</p><!-- <p>no</p> --><script>var x='<p>nope</p>';</script><style>p{}</style>end", &d, text, sizeof(text));
	CHECK(d.title && !strcmp(d.title, "The & title"));
	CHECK(strstr(text, "Head\n"));
	CHECK(strstr(text, "one two three\n"));
	CHECK(strstr(text, "end\n"));
	CHECK(!strstr(text, "nope") && !strstr(text, "no\n") && !strstr(text, "p{}"));
	doc_free(&d);

	layout("<a href='/x'>go</a> <a href=\"javascript:bad()\">js</a> <a href='#top'>top</a>", &d, text, sizeof(text));
	CHECK(d.n_targets == 1 && !strcmp(d.targets[0].url, "https://a.org/x"));
	CHECK(strstr(text, "go js top"));
	doc_free(&d);

	/* Entities and characters beyond the font. */
	layout("a&nbsp;b &lt;c&gt; &#65;&#x42; caf\xc3\xa9 \xe2\x80\x9cq\xe2\x80\x9d \xf0\x9f\x98\x80 bad\xff &nosuch;", &d, text, sizeof(text));
	CHECK(strstr(text, "a b <c> AB caf\xe9 \"q\""));
	CHECK(strstr(text, "bad\xff"));
	CHECK(strstr(text, "&nosuch;"));
	doc_free(&d);

	/* Wrapping, and a word too long for a row. */
	{
		static char long_html[6000];
		memset(long_html, 'x', 500);
		long_html[500] = ' ';
		for (int i = 0; i < 200; i++)
			memcpy(long_html + 501 + i * 5, "word ", 5);
		long_html[1501] = '\0';
		layout(long_html, &d, text, sizeof(text));
		CHECK(rows_stay_in_width(&d, WEB_COLS));
		CHECK(d.n > 15);
		doc_free(&d);
	}

	layout("<ul><li>a<li>b<ul><li>c</ul></ul><ol><li>x<li>y</ol><pre>keep  this\n  shape</pre>", &d, text, sizeof(text));
	CHECK(strstr(text, "* a\n* b\n"));
	CHECK(strstr(text, "  * c\n"));
	CHECK(strstr(text, "1. x\n2. y\n"));
	CHECK(strstr(text, "keep  this\n  shape\n"));
	doc_free(&d);

	/* Hidden things and menus. */
	layout("<nav><a href=/m>menu</a></nav><div hidden>h1</div><div style='display: none'>h2</div><p aria-hidden=true>h3</p><p>shown shown shown</p><p>2</p><p>3</p><p>4</p>", &d, text, sizeof(text));
	CHECK(strstr(text, "shown"));
	CHECK(!strstr(text, "menu") && !strstr(text, "h1") && !strstr(text, "h2") && !strstr(text, "h3"));
	doc_free(&d);

	/* A form. */
	layout("<form action='/s' method=post><input type=hidden name=h value=1><input name=q value=hi><input type=password name=p value=abc>"
	       "<input type=checkbox name=c checked><select name=l><option value=a>A<option value=b selected>B</select>"
	       "<textarea name=t>tt</textarea><button name=b value=v><i>Go</i> now</button></form>", &d, text, sizeof(text));
	CHECK(d.n_forms == 1 && d.forms[0].post && !strcmp(d.forms[0].action, "https://a.org/s"));
	CHECK(d.n_fields == 6);
	CHECK(strstr(text, "hi "));
	CHECK(!strstr(text, "abc") && strstr(text, "***"));
	CHECK(strstr(text, "[Go now]"));
	CHECK(d.n_targets == 1 && d.targets[0].kind == TARGET_SUBMIT && !strcmp(d.targets[0].name, "b"));
	for (int i = 0; i < d.n_fields; i++)
		if (!strcmp(d.fields[i].name, "l"))
			CHECK(!strcmp(d.fields[i].value, "b"));
	doc_free(&d);

	/* Pictures reserve their rows, and tiny ones don't count. */
	layout("<img src=a.png width=100 height=100 alt=pic><img src=b.png width=16 height=16><img src='data:x' data-src=c.png><img>", &d, text, sizeof(text));
	CHECK(d.n_images == 2);
	CHECK(d.images[0].n_rows == 20 && !strcmp(d.images[0].url, "https://a.org/dir/a.png"));
	CHECK(d.images[1].n_rows == 12 && !strcmp(d.images[1].url, "https://a.org/dir/c.png"));
	CHECK(strstr(text, "[image: pic]"));
	doc_free(&d);

	/* A hidden tag that has no closing tag mustn't swallow the page. */
	layout("<img aria-hidden=true src=a><hr hidden><br hidden><embed src=x><p>still here</p>", &d, text, sizeof(text));
	CHECK(strstr(text, "still here"));
	doc_free(&d);

	layout("<meta http-equiv=refresh content='0;url=/next'><p>moved</p>", &d, text, sizeof(text));
	CHECK(d.refresh && !strcmp(d.refresh, "https://a.org/next"));
	doc_free(&d);

	/* Broken markup of every kind must end cleanly. */
	static const char *const BROKEN[] = {
		"<", "<<<<", "<a", "<a href=", "<a href='", "<!--", "<!-- -", "</", "</a", "&", "&#", "&#x", "&#xffffffffff;", "&amp",
		"<script>", "<script", "<style>x", "<title>", "<title>x", "<select>", "<select name=a><option", "<textarea name=t>",
		"<button>", "<form><input name=", "<img src=", "<img src=x width=-5 height=0>", "<nav>", "<ul><ul><ul><ul><ul><ul><ul><ul><ul><ul><li>x",
		"</ul></ul></ol></b></pre></blockquote></h1>", "<pre>", "<blockquote><blockquote>", "<meta http-equiv=refresh content='x'>",
		"<a href=x><a href=y>z", "\xf0\x9f", "\xe2\x80", "<svg><svg></svg>", NULL,
	};
	for (int i = 0; BROKEN[i]; i++) {
		layout(BROKEN[i], &d, text, sizeof(text));
		CHECK(rows_stay_in_width(&d, WEB_COLS));
		doc_free(&d);
	}

	/* The agent's view has the addresses written out. */
	doc_init(&d);
	const char *page = "<a href=/x>go</a> and <img src=a.png alt=cat>";
	html_layout(page, strlen(page), "https://a.org/", (html_options){ .width = 100, .inline_urls = 1 }, &d);
	text_of(&d, text, sizeof(text));
	CHECK(strstr(text, "go <https://a.org/x>"));
	CHECK(strstr(text, "[image: cat]"));
	CHECK(d.n_images == 0);
	doc_free(&d);
}

/* Rows must be safe for the C screen code to walk: control bytes complete, runs closed. */
static int rows_well_formed(const doc *d)
{
	for (int i = 0; i < d->n; i++) {
		int in_run = 0;
		const doc_row *r = &d->rows[i];
		if (r->len > WEB_ROW_BYTES)
			return 0;
		for (int k = 0; k < r->len; k++) {
			const unsigned char c = r->b[k];
			if (c == WEB_C_LINK || c == WEB_C_FIELD) {
				if (in_run || k + 2 >= r->len)
					return 0;
				in_run = 1;
				k += 2;
			} else if (c == WEB_C_END) {
				if (!in_run)
					return 0;
				in_run = 0;
			}
		}
		if (in_run)
			return 0;
	}
	return 1;
}

static void test_flow_and_markdown(void)
{
	static char text[65536];
	doc d;
	flow f;
	doc_init(&d);
	flow_init(&f, &d, WEB_COLS);
	const char *md = "# Title\n\nSome **bold** and `code` and [a link](https://x.org/a) and https://y.org/b.\n\n- one\n- two with a line long enough that it has to wrap round to the next row\n\n```\nkeep  this\n```\n> quoted\nlast";
	doc_markdown(&f, md, strlen(md));
	flow_end(&f);
	text_of(&d, text, sizeof(text));
	CHECK(strstr(text, "Title\n"));
	CHECK(strstr(text, "Some bold and code and a link and"));
	CHECK(strstr(text, "https://y.org/b."));
	CHECK(strstr(text, "* one\n"));
	CHECK(strstr(text, "keep  this\n"));
	CHECK(strstr(text, "quoted\n"));
	CHECK(d.n_targets == 2 && !strcmp(d.targets[0].url, "https://x.org/a") && !strcmp(d.targets[1].url, "https://y.org/b"));
	CHECK(rows_well_formed(&d));
	CHECK(rows_stay_in_width(&d, WEB_COLS));
	doc_free(&d);

	/* Links wrapped over many rows, with many short links on one row. */
	doc_init(&d);
	flow_init(&f, &d, WEB_COLS);
	for (int i = 0; i < 80; i++) {
		flow_link(&f, doc_add_link(&d, "https://x/"));
		flow_text(&f, "a", 1);
		flow_link(&f, -1);
		flow_style(&f, i % 2 ? WEB_S_BOLD : WEB_S_NORMAL);
		flow_text(&f, " ", 1);
	}
	flow_end(&f);
	CHECK(rows_well_formed(&d));
	doc_free(&d);

	/* A very long unterminated code block and a stream cut off anywhere. */
	static const char *const PARTS[] = { "**", "**x", "`", "[a", "[a](", "[a](http", "[a](https://x", "```", "#", "# ", "- ", ">", "http://", "https://a", NULL };
	for (int i = 0; PARTS[i]; i++) {
		doc_init(&d);
		flow_init(&f, &d, WEB_COLS);
		doc_markdown(&f, PARTS[i], strlen(PARTS[i]));
		flow_end(&f);
		CHECK(rows_well_formed(&d));
		doc_free(&d);
	}

	/* Field rows hide secrets and stay well-formed even with odd values. */
	doc_init(&d);
	doc_add_row(&d, (const unsigned char *)"", 0);
	const int field = doc_add_field(&d, 0, "p", "s\x01\x0e\xffret that is much longer than the box it goes in, so very long indeed", 0, 1, 44);
	doc_field_row(&d, field);
	CHECK(rows_well_formed(&d));
	text_of(&d, text, sizeof(text));
	CHECK(!strstr(text, "ret"));
	doc_free(&d);
}

static int str_is(json_val v, const char *want)
{
	sb out = { 0 };
	const int ok = json_string(v, &out) && !strcmp(out.s, want);
	sb_free(&out);
	return ok;
}

static void test_json(void)
{
	const char *js = " {\"type\":\"content_block_delta\",\"index\":3,\"delta\":{\"type\":\"text_delta\",\"text\":\"a\\n\\\"b\\u00e9\\ud83d\\ude00\"},\"arr\":[1,{\"x\":[]}],\"t\":true} ";
	const size_t n = strlen(js);
	json_val v;
	CHECK(json_valid(js, n));
	CHECK(json_get(js, n, "type", &v) && str_is(v, "content_block_delta"));
	CHECK(json_get(js, n, "delta.text", &v) && str_is(v, "a\n\"b\xc3\xa9\xf0\x9f\x98\x80"));
	CHECK(json_get(js, n, "index", &v) && json_number(v) == 3);
	CHECK(json_get(js, n, "t", &v));
	CHECK(!json_get(js, n, "delta.nope", &v));
	CHECK(!json_get(js, n, "nope.x", &v));

	static const char *const BAD[] = { "", "{", "{\"a\"", "{\"a\":", "{\"a\":1", "{\"a\":1,", "[1,", "\"x", "{\"a\":\"\\", "tru", "{]", "{\"a\":1}x", "\"a\nb\"", NULL };
	for (int i = 0; BAD[i]; i++) {
		CHECK(!json_valid(BAD[i], strlen(BAD[i])));
		CHECK(!json_get(BAD[i], strlen(BAD[i]), "a.b", &v));
	}
	char deep[600];
	memset(deep, '[', sizeof(deep));
	CHECK(!json_valid(deep, sizeof(deep)));

	sb out = { 0 };
	json_quote(&out, "a\"b\\c\nd\x01\xc3\xa9\xff\xed\xa0\x80", 14);
	CHECK(!strcmp(out.s, "\"a\\\"b\\\\c\\nd\\u0001\xc3\xa9\\ufffd\\ufffd\\ufffd\\ufffd\""));
	CHECK(json_valid(out.s, out.n));
	sb_free(&out);

	const json_val bad_escape = { "\"\\u12\"", 6 };
	CHECK(!json_string(bad_escape, &out));
	sb_free(&out);
	const json_val empty = { "\"\"", 2 };
	CHECK(json_string(empty, &out) && out.n == 0);
	sb_free(&out);
}

static void test_json_each(void)
{
	const json_val arr = { " [ 1 , {\"x\":[2]},\"s\" ] ", 24 };
	json_val v;
	size_t at = 0;
	CHECK(json_each(arr, &at, &v) && v.n == 1 && v.s[0] == '1');
	CHECK(json_each(arr, &at, &v) && v.n == 9 && json_valid(v.s, v.n));
	CHECK(json_each(arr, &at, &v) && str_is(v, "s"));
	CHECK(!json_each(arr, &at, &v));
	static const char *const NOT[] = { "[]", " [ ] ", "{}", "", "[", "[,1]", "7" };
	for (size_t i = 0; i < sizeof(NOT) / sizeof(NOT[0]); i++) {
		at = 0;
		CHECK(!json_each((json_val){ NOT[i], strlen(NOT[i]) }, &at, &v));
	}
	const json_val cut = { "[1,", 3 };
	at = 0;
	CHECK(json_each(cut, &at, &v));
	CHECK(!json_each(cut, &at, &v));
}

static void chunk(gemini_reply *r, const char *js)
{
	gemini_read_chunk(js, strlen(js), r);
}

static void test_gemini_reply(void)
{
	gemini_reply r = { 0 };
	CHECK(gemini_outcome_of(&r) == GEMINI_FAILED);     /* the stream ended with no finish */

	/* Text arrives in pieces. The closing empty part isn't sent back, but one with a signature is. */
	chunk(&r, "{\"candidates\":[{\"content\":{\"role\":\"model\",\"parts\":[{\"text\":\"Hel\"}]},\"index\":0}],\"usageMetadata\":{\"promptTokenCount\":7,\"candidatesTokenCount\":1}}");
	CHECK(gemini_outcome_of(&r) == GEMINI_FAILED);
	chunk(&r, "{\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"lo\\n\"},{\"text\":\"\"}]}}]}");
	chunk(&r, "{\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"\",\"thoughtSignature\":\"sig\"}]},\"finishReason\":\"STOP\"}],"
	          "\"usageMetadata\":{\"promptTokenCount\":9,\"candidatesTokenCount\":4,\"thoughtsTokenCount\":6}}");
	CHECK(!strcmp(r.text.s, "Hello\n"));
	CHECK(!strcmp(r.parts.s, "{\"text\":\"Hel\"},{\"text\":\"lo\\n\"},{\"text\":\"\",\"thoughtSignature\":\"sig\"}"));
	CHECK(gemini_outcome_of(&r) == GEMINI_DONE);
	gemini_reply_clear(&r);
	CHECK(!r.text.n && !r.parts.n && !r.finish.n);

	/* Tool calls keep their signature when sent back; args are JSON text. */
	const char *call = "{\"functionCall\":{\"id\":\"c1\",\"name\":\"read_page\",\"args\":{\"url\":\"a.b\"}},\"thoughtSignature\":\"s1\"}";
	sb js = { 0 };
	sb_adds(&js, "{\"candidates\":[{\"content\":{\"parts\":[");
	sb_adds(&js, call);
	sb_adds(&js, ",{\"functionCall\":{\"name\":\"search_web\",\"args\":{\"query\":\"q\"}}}]},\"finishReason\":\"STOP\"}]}");
	chunk(&r, js.s);
	sb_free(&js);
	CHECK(gemini_outcome_of(&r) == GEMINI_CALLS);
	CHECK(r.n_calls == 2 && !strcmp(r.calls[0].name.s, "read_page") && !strcmp(r.calls[0].id.s, "c1"));
	CHECK(!strcmp(r.calls[0].args.s, "{\"url\":\"a.b\"}") && !r.calls[1].id.n);
	CHECK(!r.text.n && strstr(r.parts.s, call) == r.parts.s);

	/* The whole conversation comes out as a valid request. */
	sb contents = { 0 }, results = { 0 }, body = { 0 };
	gemini_add_user(&contents, "hi \"there\"", 10);
	gemini_add_model(&contents, &r);
	gemini_add_result(&results, &r.calls[0], "page \"text\"", 11, 1);
	gemini_add_result(&results, &r.calls[1], "no", 2, 0);
	gemini_add_results(&contents, &results);
	gemini_body(&body, "be \"brief\"", "[{\"functionDeclarations\":[]}]", &contents);
	CHECK(json_valid(body.s, body.n));
	json_val v, item, f;
	size_t at = 0;
	CHECK(json_get(body.s, body.n, "systemInstruction.parts", &v));
	CHECK(json_get(body.s, body.n, "generationConfig.maxOutputTokens", &v) && json_number(v) == 4000);
	CHECK(json_get(body.s, body.n, "contents", &v));
	CHECK(json_each(v, &at, &item) && json_get(item.s, item.n, "role", &f) && str_is(f, "user"));
	CHECK(json_each(v, &at, &item) && json_get(item.s, item.n, "role", &f) && str_is(f, "model"));
	CHECK(strstr(item.s, "\"thoughtSignature\":\"s1\"") != NULL);
	CHECK(json_each(v, &at, &item) && json_get(item.s, item.n, "role", &f) && str_is(f, "user"));
	CHECK(!json_each(v, &at, &item));
	CHECK(strstr(results.s, "{\"functionResponse\":{\"id\":\"c1\",\"name\":\"read_page\",\"response\":{\"result\":\"page \\\"text\\\"\"}}}") == results.s);
	CHECK(strstr(results.s, "{\"functionResponse\":{\"name\":\"search_web\",\"response\":{\"error\":\"no\"}}}") != NULL);
	sb_free(&contents);
	sb_free(&results);
	sb_free(&body);
	gemini_reply_clear(&r);

	/* How replies can end. */
	chunk(&r, "{\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"so far\"}]},\"finishReason\":\"MAX_TOKENS\"}]}");
	CHECK(gemini_outcome_of(&r) == GEMINI_CUT_OFF);
	gemini_reply_clear(&r);
	chunk(&r, "{\"candidates\":[{\"finishReason\":\"MAX_TOKENS\"}]}");
	CHECK(gemini_outcome_of(&r) == GEMINI_FAILED);
	gemini_reply_clear(&r);
	chunk(&r, "{\"candidates\":[{\"content\":{\"parts\":[{\"functionCall\":{\"name\":\"x\"}}]},\"finishReason\":\"MAX_TOKENS\"}]}");
	CHECK(gemini_outcome_of(&r) == GEMINI_FAILED);     /* a call with no answer can't stay in the history */
	gemini_reply_clear(&r);
	chunk(&r, "{\"candidates\":[{\"finishReason\":\"STOP\"}]}");
	CHECK(gemini_outcome_of(&r) == GEMINI_FAILED);
	gemini_reply_clear(&r);
	chunk(&r, "{\"candidates\":[{\"finishReason\":\"MALFORMED_FUNCTION_CALL\"}]}");
	CHECK(gemini_outcome_of(&r) == GEMINI_FAILED);
	gemini_reply_clear(&r);
	chunk(&r, "{\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"par\"}]},\"finishReason\":\"SAFETY\"}]}");
	CHECK(gemini_outcome_of(&r) == GEMINI_DECLINED);
	gemini_reply_clear(&r);
	chunk(&r, "{\"promptFeedback\":{\"blockReason\":\"OTHER\"}}");
	CHECK(gemini_outcome_of(&r) == GEMINI_DECLINED);
	gemini_reply_clear(&r);
	chunk(&r, "{\"error\":{\"code\":503,\"message\":\"overloaded\"}}");
	CHECK(!strcmp(r.error.s, "overloaded"));
	gemini_reply_clear(&r);

	/* Thoughts never reach the screen. */
	chunk(&r, "{\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"hmm\",\"thought\":true},{\"text\":\"yes\"}]},\"finishReason\":\"STOP\"}]}");
	CHECK(!strcmp(r.text.s, "yes") && strstr(r.parts.s, "hmm"));
	gemini_reply_clear(&r);

	/* Too many calls in one reply fails the turn, and nothing overruns. */
	for (int i = 0; i < GEMINI_MAX_CALLS + 3; i++)
		chunk(&r, "{\"candidates\":[{\"content\":{\"parts\":[{\"functionCall\":{\"name\":\"x\",\"args\":{}}}]},\"finishReason\":\"STOP\"}]}");
	CHECK(r.n_calls == GEMINI_MAX_CALLS && gemini_outcome_of(&r) == GEMINI_FAILED);
	gemini_reply_clear(&r);

	/* Nonsense from the network adds nothing. */
	static const char *const BAD[] = { "", "{", "[]", "{\"candidates\":3}", "{\"candidates\":[]}", "{\"candidates\":[{\"content\":{\"parts\":7}}]}",
	                                   "{\"candidates\":[{\"content\":{\"parts\":[{\"text\":3}", "{\"candidates\":[{\"finishReason\":9}]}" };
	for (size_t i = 0; i < sizeof(BAD) / sizeof(BAD[0]); i++) {
		chunk(&r, BAD[i]);
		CHECK(!r.text.n && !r.n_calls && gemini_outcome_of(&r) == GEMINI_FAILED);
		gemini_reply_clear(&r);
	}
}

static void test_gemini_forget_turns(void)
{
	sb contents = { 0 };
	size_t starts[4];
	int n = 0;
	const char *const said[] = { "aaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbb", "cccccccccccccccccccc", "dddddddddddddddddddd", "eeeeeeeeeeeeeeeeeeee" };
	for (int i = 0; i < 3; i++) {
		starts[n++] = contents.n;
		gemini_add_user(&contents, said[i], strlen(said[i]));
	}
	const size_t whole = contents.n;

	/* Under the limit, nothing goes. */
	CHECK(gemini_forget_turns(&contents, starts, n, 4, whole) == 3 && contents.n == whole);
	/* Over it, the oldest goes, and what's left is still a valid list with the right starts. */
	n = gemini_forget_turns(&contents, starts, n, 4, whole - 1);
	CHECK(n == 2 && starts[0] == 0 && !strstr(contents.s, said[0]));
	sb list = { 0 };
	sb_adds(&list, "[");
	sb_add(&list, contents.s, contents.n);
	sb_adds(&list, "]");
	CHECK(json_valid(list.s, list.n));
	sb_free(&list);
	CHECK(contents.s[starts[1]] == ',' && strstr(contents.s + starts[1], said[2]));
	/* However small the limit, the latest stays. */
	n = gemini_forget_turns(&contents, starts, n, 4, 1);
	CHECK(n == 1 && starts[0] == 0 && contents.s[0] == '{' && strstr(contents.s, said[2]));
	/* A full table makes room whatever the size. */
	for (int i = 3; i < 5; i++) {
		starts[n++] = contents.n;
		gemini_add_user(&contents, said[i], strlen(said[i]));
	}
	starts[n++] = contents.n;
	gemini_add_user(&contents, said[0], strlen(said[0]));
	n = gemini_forget_turns(&contents, starts, n, 4, 100000);
	CHECK(n == 3 && !strstr(contents.s, said[2]) && strstr(contents.s, said[3]));
	/* Nothing there at all is fine. */
	sb empty = { 0 };
	CHECK(gemini_forget_turns(&empty, starts, 0, 4, 1) == 0);
	sb_free(&contents);
}

static void test_ascii(void)
{
	CHECK(ascii_tile(0, 0, 0) == 0);
	const unsigned white = ascii_tile(255, 255, 255);
	CHECK(white / WEB_SHADES == 7 && white % WEB_SHADES == WEB_SHADES - 1);
	CHECK(ascii_tile(255, 0, 0) / WEB_SHADES == 0);
	CHECK(ascii_tile(0, 255, 0) / WEB_SHADES == 1);
	CHECK(ascii_tile(0, 0, 255) / WEB_SHADES == 2);
	CHECK(ascii_tile(255, 255, 0) / WEB_SHADES == 3);
	CHECK(ascii_tile(0, 200, 200) / WEB_SHADES == 5);
	for (unsigned v = 0; v < 256; v += 5)
		CHECK(ascii_tile(v, 255 - v, v / 2) < WEB_PALETTE * WEB_SHADES);

	/* A wide picture gets centred vertically, with both sides of it reached. */
	enum { W = 300, H = 100, COLS = 60, ROWS = 40 };
	static uint8_t px[W * H * 3], out[COLS * ROWS];
	memset(px, 255, sizeof(px));
	ascii_image(px, W, H, COLS, ROWS, out);
	CHECK(out[0] == 0 && out[(ROWS / 2) * COLS] != 0 && out[(ROWS / 2) * COLS + COLS - 1] != 0);
	/* A tall one fits the height; tiny and huge don't go out of bounds. */
	ascii_image(px, 1, 1, COLS, ROWS, out);
	ascii_image(px, 3, 100, COLS, ROWS, out);
	CHECK(out[COLS / 2] != 0 && out[(ROWS - 1) * COLS + COLS / 2] != 0);
	ascii_image(px, 300, 1, COLS, ROWS, out);
	/* A dim, low-contrast picture is stretched to use the whole range of shades. */
	for (int i = 0; i < W * H; i++)
		memset(px + i * 3, i % W < W / 2 ? 90 : 130, 3);
	ascii_image(px, W, H, COLS, ROWS, out);
	CHECK(out[(ROWS / 2) * COLS + 2] == 0);
	CHECK(out[(ROWS / 2) * COLS + COLS - 3] % WEB_SHADES == WEB_SHADES - 1);
	ascii_image(px, 0, 0, COLS, ROWS, out);
}

int main(void)
{
	test_url();
	test_html();
	test_flow_and_markdown();
	test_json();
	test_json_each();
	test_gemini_reply();
	test_gemini_forget_turns();
	test_ascii();
	printf("%d checks, %d failures\n", checks, failures);
	return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
