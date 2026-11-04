/* Calculator behaviour: what each key does to the state. Drawing is in calculator_view.c. */
#include <string.h>

#include "calculator_state.h"
#include "trend/expr.h"

const unsigned char CALC_KEYCODES[CALC_KEYS] = {
	'C', '(', ')', TR_CALC_DIV,
	'7', '8', '9', TR_CALC_MUL,
	'4', '5', '6', TR_CALC_MINUS,
	'1', '2', '3', '+',
	'0', '.', TR_CALC_DEL, '=',
};

/* Animation lengths in seconds. The view reads the same timings. */
#define TYPE_T 0.18
#define SCROLL_T 0.20
#define SHAKE_T 0.35
#define DECODE_STEP 0.03
#define DECODE_CHAR 0.16
#define CLEAR_STEP 0.018
#define CLEAR_CHAR 0.16

size_t tr_calc_size(void)
{
	return sizeof(tr_calc);
}

const char *tr_calc_expr(const tr_calc *s)
{
	return s->expr;
}

void tr_calc_init(tr_calc *out)
{
	memset(out, 0, sizeof(*out));
	out->pressed = -1;
	for (int i = 0; i < CALC_KEYS; i++)
		out->released[i] = -1.0;
	out->t_type = out->t_eq = out->t_err = out->t_clear = out->t_scroll = -1.0;
	out->cleared.tone = TONE_PREVIEW;
	out->cleared.size = 54;
}

/* ---- text derived from the state ---- */

static int is_operator(char c)
{
	return c == '+' || c == '-' || c == '*' || c == '/';
}

static char pretty_operator(char c)
{
	return c == '/' ? (char)TR_CALC_DIV : c == '*' ? (char)TR_CALC_MUL : c == '-' ? (char)TR_CALC_MINUS : c;
}

/* "12*(3-4)" becomes "12 x (3 - 4)", with real symbols and spaces around operators. */
static void pretty(const char *expr, char *out, size_t cap)
{
	size_t n = 0;
	for (const char *p = expr; *p && n + 4 < cap; p++) {
		if (is_operator(*p)) {
			if (n && out[n - 1] == '(') {      /* no space straight after a bracket */
				out[n++] = pretty_operator(*p);
			} else {
				if (n)
					out[n++] = ' ';    /* nor at the very start */
				out[n++] = pretty_operator(*p);
			}
			out[n++] = ' ';
		} else {
			out[n++] = *p;
		}
	}
	while (n && out[n - 1] == ' ')
		n--;
	out[n] = '\0';
}

/* Keep the end of a long line, marking the cut with an ellipsis. */
static void last_chars(const char *src, int keep, char *out, size_t cap)
{
	const size_t len = strlen(src);
	if (len <= (size_t)keep + 1) {
		calc_copy(out, cap, src);
	} else {
		const char mark[2] = { (char)TR_CALC_ELLIPSIS, '\0' };
		calc_copy(out, cap, mark);
		calc_append(out, cap, src + len - (size_t)keep);
	}
}

calc_lines calc_lines_of(const tr_calc *s)
{
	calc_lines l;
	char result[CALC_EXPR_MAX] = "";
	char expr[CALC_PRETTY_MAX];
	if (s->just_eq) {
		calc_copy(result, sizeof(result), s->expr);
		calc_copy(expr, sizeof(expr), s->shown_expr);
		l.tone = strcmp(s->expr, "Error") == 0 ? TONE_ERROR : TONE_ACCENT;
	} else {
		if (s->expr[0] && strcmp(s->expr, "Error") != 0)
			tr_expr_result(s->expr, result, sizeof(result));
		pretty(s->expr, expr, sizeof(expr));
		l.tone = TONE_PREVIEW;
	}
	last_chars(expr, 22, l.expr, sizeof(l.expr));
	l.text[0] = '\0';
	if (result[0]) {
		calc_copy(l.text, sizeof(l.text), "= ");
		calc_append(l.text, sizeof(l.text), result);
	}
	l.size = strlen(l.text) < 13 ? 54 : 34;
	return l;
}

/* The newest result stays on the prompt line until the next key, then scrolls into the history. */
calc_hist_lines calc_hist_lines_of(const tr_calc *s)
{
	calc_hist_lines h;
	const int end = s->just_eq ? s->n_history - 1 : s->n_history;
	const int start = end - CALC_HIST_LINES < 0 ? 0 : end - CALC_HIST_LINES;
	h.n = 0;
	for (int i = start; i < end; i++) {
		char line[CALC_PRETTY_MAX + CALC_RESULT_MAX + 3];
		calc_copy(line, sizeof(line), s->history[i].expr);
		calc_append(line, sizeof(line), " = ");
		calc_append(line, sizeof(line), s->history[i].result);
		last_chars(line, 31, h.line[h.n++], CALC_HIST_LINE_MAX);
	}
	return h;
}

static int hist_contains(const calc_hist_lines *h, const char *line)
{
	for (int i = 0; i < h->n; i++)
		if (strcmp(h->line[i], line) == 0)
			return 1;
	return 0;
}

static int hist_equal(const calc_hist_lines *a, const calc_hist_lines *b)
{
	if (a->n != b->n)
		return 0;
	for (int i = 0; i < a->n; i++)
		if (strcmp(a->line[i], b->line[i]) != 0)
			return 0;
	return 1;
}

/* ---- key presses ---- */

static void extend_animation(tr_calc *s, double now, double seconds)
{
	if (now + seconds > s->anim_until)
		s->anim_until = now + seconds;
}

static void press_clear(tr_calc *s, double now)
{
	const calc_lines l = calc_lines_of(s);
	if (l.expr[0] || l.text[0]) {
		const size_t a = strlen(l.expr), b = strlen(l.text);
		s->cleared = l;
		s->t_clear = now;
		extend_animation(s, now, CLEAR_STEP * (double)(a > b ? a : b) + CLEAR_CHAR + 0.05);
	}
	s->expr[0] = s->shown_expr[0] = '\0';
	s->just_eq = 0;
}

static void press_delete(tr_calc *s)
{
	const size_t n = strlen(s->expr);
	if (s->just_eq)
		s->expr[0] = '\0';
	else if (n)
		s->expr[n - 1] = '\0';
	s->just_eq = 0;
}

static void remember(tr_calc *s, const char *expr, const char *result)
{
	if (s->n_history == CALC_HISTORY) {
		memmove(&s->history[0], &s->history[1], sizeof(s->history[0]) * (CALC_HISTORY - 1));
		s->n_history--;
	}
	calc_copy(s->history[s->n_history].expr, CALC_PRETTY_MAX, expr);
	calc_copy(s->history[s->n_history].result, CALC_RESULT_MAX, result);
	s->n_history++;
}

static void press_equals(tr_calc *s, double now)
{
	char result[CALC_RESULT_MAX];
	if (!s->expr[0] || s->just_eq)
		return;
	const int ok = tr_expr_result(s->expr, result, sizeof(result));
	pretty(s->expr, s->shown_expr, sizeof(s->shown_expr));
	if (ok) {
		remember(s, s->shown_expr, result);
		s->t_eq = now;
		extend_animation(s, now, DECODE_STEP * (double)strlen(result) + DECODE_CHAR + 0.3);
		calc_copy(s->expr, sizeof(s->expr), result);
	} else {
		s->t_err = now;
		extend_animation(s, now, SHAKE_T);
		calc_copy(s->expr, sizeof(s->expr), "Error");
	}
	s->just_eq = 1;
}

static char ascii_of(unsigned key)
{
	return key == TR_CALC_DIV ? '/' : key == TR_CALC_MUL ? '*' : key == TR_CALC_MINUS ? '-' : (char)key;
}

static void press_character(tr_calc *s, unsigned key, double now)
{
	const char c = ascii_of(key);
	const int starts_fresh = strcmp(s->expr, "Error") == 0 ||
	                         (s->just_eq && ((c >= '0' && c <= '9') || c == '.' || c == '('));
	if (starts_fresh)
		s->expr[0] = '\0';
	size_t n = strlen(s->expr);
	if (is_operator(c) && n && is_operator(s->expr[n - 1]))
		s->expr[--n] = '\0';       /* replace a trailing operator */
	if (n < 40) {
		s->expr[n] = c;
		s->expr[n + 1] = '\0';
		s->t_type = now;
		extend_animation(s, now, TYPE_T);
	}
	s->just_eq = 0;
}

void tr_calc_press(const tr_calc *in, tr_calc *out, unsigned key, double now)
{
	tr_calc s = *in;
	const calc_hist_lines before = calc_hist_lines_of(&s);
	if (key == 'C')
		press_clear(&s, now);
	else if (key == TR_CALC_DEL)
		press_delete(&s);
	else if (key == '=')
		press_equals(&s, now);
	else
		press_character(&s, key, now);

	const calc_hist_lines after = calc_hist_lines_of(&s);
	if (after.n && !hist_equal(&after, &before) && !hist_contains(&before, after.line[after.n - 1])) {
		s.scroll_from = before;    /* a new line joins the history */
		s.t_scroll = now;
		extend_animation(&s, now, SCROLL_T);
	}
	*out = s;
}

/* ---- touches ---- */

static int key_at(int x, int y)
{
	if (x < KEY_X || y < KEY_Y)
		return -1;
	const int c = (x - KEY_X) / (KEY_W + KEY_GAP_X), r = (y - KEY_Y) / (KEY_H + KEY_GAP_Y);
	if (c >= CALC_COLS || r >= CALC_ROWS)
		return -1;
	const int in_key = x <= KEY_X + c * (KEY_W + KEY_GAP_X) + KEY_W &&
	                   y <= KEY_Y + r * (KEY_H + KEY_GAP_Y) + KEY_H;
	return in_key ? r * CALC_COLS + c : -1;
}

static void release_key(tr_calc *s, double now)
{
	if (s->pressed >= 0)
		s->released[s->pressed] = now;
	s->pressed = -1;
}

void tr_calc_touch(const tr_calc *in, tr_calc *out, int event, int x, int y, double now)
{
	tr_calc s = *in;
	const int k = key_at(x, y);
	if (event == TR_TOUCH_DOWN) {
		s.pressed = k;
	} else if (event == TR_TOUCH_MOVE) {
		if (k != s.pressed)
			release_key(&s, now);
	} else {
		if (k >= 0 && k == s.pressed)
			tr_calc_press(&s, &s, CALC_KEYCODES[k], now);
		release_key(&s, now);
	}
	*out = s;
}

/* ---- redraw key ---- */

static uint64_t hash_bytes(uint64_t h, const void *data, size_t n)
{
	const unsigned char *p = data;
	for (size_t i = 0; i < n; i++)
		h = (h ^ p[i]) * 1099511628211ull;  /* FNV-1a */
	return h;
}

static uint64_t hash_int(uint64_t h, int v)
{
	return hash_bytes(h, &v, sizeof(v));
}

uint64_t tr_calc_frame_key(const tr_calc *s, double now)
{
	int animating = now < s->anim_until;
	for (int i = 0; i < CALC_KEYS && !animating; i++)
		animating = s->released[i] >= 0.0 && now - s->released[i] < CALC_FADE;

	uint64_t h = 14695981039346656037ull;
	h = hash_bytes(h, s->expr, strlen(s->expr));
	h = hash_int(h, s->pressed);
	h = hash_int(h, s->just_eq);
	h = hash_int(h, s->n_history);
	h = hash_int(h, (int)(now / CALC_BLINK) % 2);
	return hash_int(h, animating ? (int)(now * 60.0) : 0);
}
