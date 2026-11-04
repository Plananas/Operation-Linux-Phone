/* webd: everything in the Web app that touches the internet. It runs as its own unprivileged user, twice: once
 * as the browser and once as the chat agent, so that one can work while the other waits. See web_wire.h for
 * what it says to the shell.
 *
 *   webd web|agent [-u user] [-k keyfile] [-a api-base] [-m model]
 *
 * Browser commands, one per line:
 *   G <scroll> <typed address>   go there (a page keeps its scroll position for coming back to)
 *   F <scroll> <target>          follow a link or press a form button
 *   I <field> <text>             a form field's new value
 *   B <scroll>, W <scroll>       back, forward
 *   R, X                         reload, stop
 * Agent commands: S <text> (send), P <url> (the page in the browser), F <target> (a link), C (stop), N (new chat).
 */
#include <errno.h>
#include <grp.h>
#include <pwd.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <unistd.h>

#include "agent.h"
#include "ascii.h"
#include "fetch.h"
#include "html.h"
#include "url.h"
#include "wire.h"

enum {
	NET_GROUP = 3003,              /* ANDROID_PARANOID_NETWORK: only this group may open sockets */
	MEMORY_LIMIT = 256 * 1024 * 1024,
	PAGE_MAX = 8 * 1024 * 1024, IMAGE_MAX = 3 * 1024 * 1024,
	HISTORY_MAX = 32, KEEP_NEAR = 3, REFRESH_MAX = 3, TIMEOUT_S = 20, EMPTY_ROWS = 6,
};

static const char START_PAGE[] =
	"<h2>TREND browser</h2><p>Type an address in the box below, or try one of these. Plain, light sites work best: "
	"there's no JavaScript here.</p><ul>"
	"<li><a href='https://en.m.wikipedia.org/'>Wikipedia</a>"
	"<li><a href='https://news.ycombinator.com/'>Hacker News</a>"
	"<li><a href='https://lite.cnn.com/'>CNN Lite</a>"
	"<li><a href='https://text.npr.org/'>NPR Text</a>"
	"<li><a href='https://html.duckduckgo.com/html/'>DuckDuckGo</a>"
	"<li><a href='https://lobste.rs/'>Lobsters</a>"
	"</ul>";

#define START_URL "about:start"

typedef struct {
	char *url;
	char *post;                    /* the form data that made this page, if any */
	unsigned scroll;
	doc *d;                        /* NULL once it's far enough back to fetch again */
	int images_tried;
} entry;

typedef struct {
	cmd_reader cmds;
	entry history[HISTORY_MAX];
	int n, cur;
	char pending[8192];
	int has_pending;
} browser;

static void free_doc(entry *e)
{
	if (e->d) {
		doc_free(e->d);
		free(e->d);
		e->d = NULL;
	}
}

static int on_watch(void *ctx)
{
	browser *b = ctx;
	cmd_fill(&b->cmds, 0);
	if (b->cmds.closed)
		_exit(0);
	if (!b->has_pending && cmd_next(&b->cmds, b->pending, sizeof(b->pending)))
		b->has_pending = 1;
	return b->has_pending;
}

static void on_progress(void *ctx, size_t received)
{
	static size_t last_kb;
	(void)ctx;
	const size_t kb = received / 1024;
	if (kb >= last_kb + 64 || kb < last_kb) {
		char text[48];
		last_kb = kb;
		snprintf(text, sizeof(text), "reading %zu KB", kb);
		wire_status(WEB_BUSY, text);
	}
}

static void show_entry(const entry *e)
{
	wire_reset();
	const int start = !strcmp(e->url, START_URL);
	wire_addr(!strncmp(e->url, "https:", 6), start ? "" : e->url);
	for (int i = 0; i < e->d->n; i++)
		wire_row(i, &e->d->rows[i]);
	wire_scroll(e->scroll);
}

static doc *error_doc(const char *headline, const char *detail)
{
	doc *d = calloc(1, sizeof(*d));
	if (!d)
		abort();
	flow f;
	flow_init(&f, d, WEB_COLS);
	flow_style(&f, WEB_S_ERROR);
	flow_text(&f, headline, strlen(headline));
	flow_blank(&f);
	flow_style(&f, WEB_S_DIM);
	flow_text(&f, detail, strlen(detail));
	flow_end(&f);
	return d;
}

static doc *layout_page(const char *html, size_t n, const char *base)
{
	doc *d = calloc(1, sizeof(*d));
	if (!d)
		abort();
	html_layout(html, n, base, (html_options){ .width = WEB_COLS }, d);
	if (d->n < EMPTY_ROWS) {       /* all menus, maybe: better those than nothing */
		char *refresh = d->refresh ? strdup(d->refresh) : NULL;
		doc_free(d);
		html_layout(html, n, base, (html_options){ .width = WEB_COLS, .keep_nav = 1 }, d);
		if (!d->refresh)
			d->refresh = refresh;
		else
			free(refresh);
	}
	if (d->n == 0) {
		doc_free(d);
		free(d);
		return error_doc("Nothing to show", "This page has no text without JavaScript, which this browser doesn't run.");
	}
	return d;
}

static doc *text_page(const char *text, size_t n)
{
	doc *d = calloc(1, sizeof(*d));
	if (!d)
		abort();
	flow f;
	flow_init(&f, d, WEB_COLS);
	f.pre = 1;
	flow_text(&f, text, n);
	flow_end(&f);
	return d;
}

static doc *image_page(const char *url)
{
	doc *d = calloc(1, sizeof(*d));
	if (!d)
		abort();
	for (int i = 0; i < 20; i++)
		doc_add_row(d, (const unsigned char *)"", 0);
	doc_add_image(d, url, 0, 20);
	return d;
}

/* Fetch the current entry and make its document. Returns 0 if a newer command interrupted it. */
static int load_entry(browser *b, entry *e)
{
	char url[4096], final[4096];
	snprintf(url, sizeof(url), "%s", e->url);
	free_doc(e);
	e->images_tried = 0;
	if (!strcmp(url, START_URL)) {
		e->d = layout_page(START_PAGE, sizeof(START_PAGE) - 1, "https://localhost/");
		show_entry(e);
		wire_status(WEB_IDLE, "");
		return 1;
	}
	for (int hop = 0; hop <= REFRESH_MAX; hop++) {
		char host[256], text[300];
		url_host(url, host, sizeof(host));
		snprintf(text, sizeof(text), "loading %s", host);
		wire_status(WEB_BUSY, text);
		net_response resp;
		net_request req = { .url = url, .gzip = 1, .timeout_s = TIMEOUT_S, .max_body = PAGE_MAX, .allow_private = hop == 0,
		                    .watch_fd = 0, .cancel = on_watch, .on_progress = on_progress, .ctx = b };
		if (hop == 0 && e->post) {
			req.method = "POST";
			req.headers = "Content-Type: application/x-www-form-urlencoded\r\n";
			req.body = e->post;
			req.body_n = strlen(e->post);
		}
		const int r = fetch_follow(req, &resp, final);
		if (r == NET_CANCELLED) {
			net_response_free(&resp);
			wire_status(WEB_IDLE, "");
			return 0;
		}
		if (r != NET_OK) {
			e->d = error_doc("Couldn't load that", resp.error);
		} else if (strstr(resp.content_type, "html") || !resp.content_type[0]) {
			e->d = layout_page(resp.body.s ? resp.body.s : "", resp.body.n, final);
		} else if (!strncmp(resp.content_type, "text/", 5) || strstr(resp.content_type, "json") || strstr(resp.content_type, "xml")) {
			e->d = text_page(resp.body.s ? resp.body.s : "", resp.body.n);
		} else if (!strncmp(resp.content_type, "image/", 6)) {
			e->d = image_page(final);
		} else {
			char detail[256];
			snprintf(detail, sizeof(detail), "This browser can't show %.128s.", resp.content_type);
			e->d = error_doc("Can't open that", detail);
		}
		net_response_free(&resp);
		if (strcmp(e->url, final)) {
			free(e->url);
			e->url = strdup(final);
		}
		if (!e->d->refresh || hop == REFRESH_MAX)
			break;
		snprintf(url, sizeof(url), "%s", e->d->refresh);
		free_doc(e);
	}
	show_entry(e);
	wire_status(WEB_IDLE, "");
	return 1;
}

static void trim_far_docs(browser *b)
{
	for (int i = 0; i < b->n; i++)
		if (abs(i - b->cur) > KEEP_NEAR)
			free_doc(&b->history[i]);
}

/* Add a new page after the current one, dropping any forward history. */
static entry *push(browser *b, const char *url, const char *post)
{
	for (int i = b->cur + 1; i < b->n; i++) {
		free_doc(&b->history[i]);
		free(b->history[i].url);
		free(b->history[i].post);
	}
	b->n = b->cur + 1;
	if (b->n == HISTORY_MAX) {
		free_doc(&b->history[0]);
		free(b->history[0].url);
		free(b->history[0].post);
		memmove(b->history, b->history + 1, (HISTORY_MAX - 1) * sizeof(entry));
		b->n--;
	}
	entry *e = &b->history[b->n];
	memset(e, 0, sizeof(*e));
	e->url = strdup(url);
	e->post = post ? strdup(post) : NULL;
	b->cur = b->n++;
	trim_far_docs(b);
	return e;
}

static void go_to(browser *b, const char *url, const char *post)
{
	load_entry(b, push(b, url, post));
}

static void step(browser *b, int to)
{
	if (to < 0 || to >= b->n)
		return;
	b->cur = to;
	entry *e = &b->history[to];
	if (e->d) {
		show_entry(e);
		wire_status(WEB_IDLE, "");
	} else {
		load_entry(b, e);
	}
	trim_far_docs(b);
}

static void add_pair(sb *q, const char *name, const char *value)
{
	char *n = malloc(strlen(name) * 3 + 1), *v = malloc(strlen(value) * 3 + 1);
	if (!n || !v)
		abort();
	url_encode(name, 1, n, strlen(name) * 3 + 1);
	url_encode(value, 1, v, strlen(value) * 3 + 1);
	if (q->n)
		sb_adds(q, "&");
	sb_adds(q, n);
	sb_adds(q, "=");
	sb_adds(q, v);
	free(n);
	free(v);
}

static void submit_form(browser *b, int form, const char *button_name, const char *button_value)
{
	const doc *d = b->history[b->cur].d;
	if (!d || form < 0 || form >= d->n_forms)
		return;
	sb q = { 0 };
	for (int i = 0; i < d->n_fields; i++)
		if (d->fields[i].form == form)
			add_pair(&q, d->fields[i].name, d->fields[i].value);
	if (button_name)
		add_pair(&q, button_name, button_value ? button_value : "");
	char *action = strdup(d->forms[form].action);
	const int post = d->forms[form].post;
	if (post) {
		go_to(b, action, q.s ? q.s : "");
	} else {
		sb target = { 0 };
		sb_add(&target, action, strcspn(action, "?"));
		sb_adds(&target, "?");
		if (q.s)
			sb_adds(&target, q.s);
		if (target.n < 4000)
			go_to(b, target.s, NULL);
		sb_free(&target);
	}
	free(action);
	sb_free(&q);
}

static void follow(browser *b, int target)
{
	const doc *d = b->cur < b->n ? b->history[b->cur].d : NULL;
	if (!d || target < 0 || target >= d->n_targets)
		return;
	const doc_target *t = &d->targets[target];
	if (t->kind == TARGET_LINK) {
		char *url = strdup(t->url);
		go_to(b, url, NULL);
		free(url);
	} else {
		char *name = t->name ? strdup(t->name) : NULL, *value = t->value ? strdup(t->value) : NULL;
		submit_form(b, t->form, name, value);
		free(name);
		free(value);
	}
}

static void set_field(browser *b, int field, const char *text)
{
	doc *d = b->cur < b->n ? b->history[b->cur].d : NULL;
	if (!d || field < 0 || field >= d->n_fields || d->fields[field].row < 0)
		return;
	doc_field *f = &d->fields[field];
	free(f->value);
	f->value = strdup(text);
	doc_field_row(d, field);
	wire_row(f->row, &d->rows[f->row]);
	/* One box to fill in, as in a search form: Done on the keyboard is all it needs. */
	int boxes = 0;
	for (int i = 0; i < d->n_fields; i++)
		boxes += d->fields[i].form == f->form && d->fields[i].row >= 0;
	if (boxes == 1 && text[0])
		submit_form(b, f->form, NULL, NULL);
}

static void handle(browser *b, const char *line)
{
	char *rest;
	entry *cur = b->cur < b->n ? &b->history[b->cur] : NULL;
	const char kind = line[0];
	const char *arg = line[1] == ' ' ? line + 2 : "";
	switch (kind) {
	case 'G': {
		const unsigned long scroll = strtoul(arg, &rest, 10);
		char url[4096];
		if (cur)
			cur->scroll = (unsigned)scroll;
		while (*rest == ' ')
			rest++;
		if (url_from_typed(rest, url, sizeof(url))) {
			go_to(b, url, NULL);
		} else {
			entry *e = push(b, START_URL, NULL);
			e->d = error_doc("That isn't a web address", rest);
			show_entry(e);
		}
		break;
	}
	case 'F': {
		const unsigned long scroll = strtoul(arg, &rest, 10);
		if (cur)
			cur->scroll = (unsigned)scroll;
		follow(b, atoi(rest));
		break;
	}
	case 'I': {
		const int field = (int)strtol(arg, &rest, 10);
		if (*rest == ' ')
			rest++;
		set_field(b, field, rest);
		break;
	}
	case 'B':
	case 'W':
		if (cur)
			cur->scroll = (unsigned)strtoul(arg, NULL, 10);
		step(b, b->cur + (kind == 'B' ? -1 : 1));
		break;
	case 'R':
		if (cur) {
			cur->scroll = 0;
			load_entry(b, cur);
		}
		break;
	default:
		break;
	}
}

/* Fetch the next picture on this page. Returns 0 if there's nothing left to do. */
static int fetch_one_image(browser *b)
{
	if (b->cur >= b->n)
		return 0;
	entry *e = &b->history[b->cur];
	doc *d = e->d;
	if (!d)
		return 0;
	doc_image *img = NULL;
	for (int i = 0; i < d->n_images && !img; i++)
		if (!d->images[i].done)
			img = &d->images[i];
	if (!img || e->images_tried >= HTML_IMAGES_MAX) {
		return 0;
	}
	char text[64], final[4096];
	e->images_tried++;
	snprintf(text, sizeof(text), "picture %d", e->images_tried);
	wire_status(WEB_BACKGROUND, text);
	net_response resp;
	net_request req = { .url = img->url, .timeout_s = TIMEOUT_S, .max_body = IMAGE_MAX, .watch_fd = 0, .cancel = on_watch, .ctx = b };
	const int r = fetch_follow(req, &resp, final);
	if (r == NET_CANCELLED) {
		e->images_tried--;
		net_response_free(&resp);
		return 1;
	}
	img->done = 1;
	if (r == NET_OK && resp.status == 200 && resp.body.n) {
		const int strips = img->n_rows * WEB_ART_ROWS;
		uint8_t *tiles = malloc((size_t)strips * WEB_ART_COLS);
		if (tiles && fetch_decode_art(resp.body.s, resp.body.n, strips, tiles)) {
			for (int i = 0; i < img->n_rows; i++) {
				doc_row *row = &d->rows[img->row + i];
				row->b[0] = WEB_ART_MARK;
				memcpy(row->b + 1, tiles + (size_t)(i * WEB_ART_ROWS) * WEB_ART_COLS, WEB_ART_ROWS * WEB_ART_COLS);
				row->len = 1 + WEB_ART_ROWS * WEB_ART_COLS;
				wire_row(img->row + i, row);
			}
		}
		free(tiles);
	}
	net_response_free(&resp);
	return 1;
}

static void browser_main(void)
{
	browser *b = calloc(1, sizeof(*b));
	char line[8192];
	if (!b)
		abort();
	wire_status(WEB_IDLE, "");
	go_to(b, START_URL, NULL);
	for (;;) {
		if (b->has_pending) {
			b->has_pending = 0;
			snprintf(line, sizeof(line), "%s", b->pending);
			handle(b, line);
			continue;
		}
		cmd_fill(&b->cmds, 0);
		if (cmd_next(&b->cmds, line, sizeof(line))) {
			handle(b, line);
			continue;
		}
		if (b->cmds.closed)
			return;
		if (fetch_one_image(b)) {
			if (!b->has_pending)
				wire_status(WEB_IDLE, "");
			continue;
		}
		cmd_fill(&b->cmds, 1);
	}
}

/* ---- starting up ---- */

static char *read_key(const char *path)
{
	static char key[512];
	FILE *f = path ? fopen(path, "r") : NULL;
	if (!f)
		return NULL;
	const size_t n = fread(key, 1, sizeof(key) - 1, f);
	fclose(f);
	key[n] = '\0';
	key[strcspn(key, " \r\n\t")] = '\0';
	return key[0] ? key : NULL;
}

static void give_up_root(const char *user)
{
	if (geteuid() != 0)
		return;
	const struct passwd *pw = getpwnam(user ? user : "");
	const gid_t groups[1] = { NET_GROUP };
	if (!pw || setgroups(1, groups) || setgid(pw->pw_gid) || setuid(pw->pw_uid) || setuid(0) == 0) {
		fprintf(stderr, "webd: couldn't give up root\n");
		exit(1);
	}
}

int main(int argc, char **argv)
{
	const char *user = NULL, *keyfile = NULL, *base = "https://api.anthropic.com", *model = "claude-opus-5-5";
	if (argc < 2) {
		fprintf(stderr, "usage: webd web|agent [-u user] [-k keyfile] [-a api-base] [-m model]\n");
		return 2;
	}
	const char *mode = argv[1];
	int opt;
	optind = 2;
	while ((opt = getopt(argc, argv, "u:k:a:m:")) != -1) {
		if (opt == 'u') user = optarg;
		else if (opt == 'k') keyfile = optarg;
		else if (opt == 'a') base = optarg;
		else if (opt == 'm') model = optarg;
		else return 2;
	}
	signal(SIGPIPE, SIG_IGN);
	char *key = !strcmp(mode, "agent") ? read_key(keyfile) : NULL;     /* before losing the right to */
	give_up_root(user);
	prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0);
	prctl(PR_SET_DUMPABLE, 0, 0, 0, 0);    /* the key stays out of core files */
	prctl(PR_SET_PDEATHSIG, SIGTERM, 0, 0, 0);
	if (getppid() == 1)
		return 0;
	const struct rlimit memory = { MEMORY_LIMIT, MEMORY_LIMIT }, no_core = { 0, 0 };
	setrlimit(RLIMIT_AS, &memory);
	setrlimit(RLIMIT_CORE, &no_core);
	if (nice(5) == -1 && errno)
		errno = 0;             /* the screen comes first */
	if (!strcmp(mode, "agent")) {
		const agent_config cfg = { key, base, model };
		agent_main(&cfg);
	} else {
		browser_main();
	}
	return 0;
}
