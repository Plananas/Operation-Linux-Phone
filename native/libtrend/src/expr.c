/* A recursive-descent parser. Each function takes the text position by value and returns the value
 * and the new position, or ok = 0.
 *
 *   sum     := product (("+" | "-") product)*
 *   product := unary (("*" | "/") unary)*
 *   unary   := ("+" | "-") unary | atom
 *   atom    := number | "(" sum ")"
 */
#include "trend/expr.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
	double value;
	const char *next;
	int ok;
} parsed;

static const parsed FAILED = { 0.0, NULL, 0 };

static inline int is_digit(char c) { return c >= '0' && c <= '9'; }

static const char *skip_digits(const char *p)
{
	while (is_digit(*p))
		p++;
	return p;
}

/* An integer may not have a leading zero unless it is all zeros: "007" is an error, "00" and "007.5"
 * are not. */
static int bad_leading_zero(const char *start, const char *end)
{
	if (*start != '0')
		return 0;
	for (const char *p = start; p < end; p++)
		if (*p != '0')
			return 1;
	return 0;
}

static parsed parse_number(const char *start)
{
	const char *p = skip_digits(start);
	const int whole_digits = (int)(p - start);
	int is_float = 0, frac_digits = 0;
	if (*p == '.') {
		const char *frac = p + 1;
		p = skip_digits(frac);
		frac_digits = (int)(p - frac);
		is_float = 1;
	}
	if (whole_digits + frac_digits == 0)
		return FAILED;
	if (*p == 'e') {
		const char *q = p + 1;
		if (*q == '+' || *q == '-')
			q++;
		if (!is_digit(*q))
			return FAILED;
		p = skip_digits(q);
		is_float = 1;
	}
	if (!is_float && bad_leading_zero(start, p))
		return FAILED;

	char literal[64];
	const size_t n = (size_t)(p - start);
	if (n >= sizeof(literal))
		return FAILED;
	memcpy(literal, start, n);
	literal[n] = '\0';
	return (parsed){ strtod(literal, NULL), p, 1 };
}

static parsed parse_sum(const char *p);

static parsed parse_atom(const char *p)
{
	if (*p != '(')
		return parse_number(p);
	const parsed inner = parse_sum(p + 1);
	if (!inner.ok || *inner.next != ')')
		return FAILED;
	return (parsed){ inner.value, inner.next + 1, 1 };
}

static parsed parse_unary(const char *p)
{
	if (*p != '+' && *p != '-')
		return parse_atom(p);
	const parsed operand = parse_unary(p + 1);
	if (!operand.ok)
		return FAILED;
	return (parsed){ *p == '-' ? -operand.value : operand.value, operand.next, 1 };
}

static parsed parse_product(const char *p)
{
	parsed left = parse_unary(p);
	while (left.ok && (*left.next == '*' || *left.next == '/')) {
		const char op = *left.next;
		const parsed right = parse_unary(left.next + 1);
		if (!right.ok || (op == '/' && right.value == 0.0))
			return FAILED;
		left = (parsed){ op == '*' ? left.value * right.value : left.value / right.value, right.next, 1 };
	}
	return left;
}

static parsed parse_sum(const char *p)
{
	parsed left = parse_product(p);
	while (left.ok && (*left.next == '+' || *left.next == '-')) {
		const char op = *left.next;
		const parsed right = parse_product(left.next + 1);
		if (!right.ok)
			return FAILED;
		left = (parsed){ op == '+' ? left.value + right.value : left.value - right.value, right.next, 1 };
	}
	return left;
}

int tr_expr_eval(const char *expr, double *value)
{
	const parsed result = parse_sum(expr);
	if (!result.ok || *result.next != '\0')
		return 0;
	*value = result.value;
	return 1;
}

void tr_number_format(double value, char *out, size_t cap)
{
	if (value == 0.0)
		snprintf(out, cap, "0");           /* never "-0" */
	else if (isfinite(value) && fabs(value) < 1e15 && value == floor(value))
		snprintf(out, cap, "%.0f", value);
	else
		snprintf(out, cap, "%.10g", value);
}

int tr_expr_result(const char *expr, char *out, size_t cap)
{
	double value;
	out[0] = '\0';
	if (!tr_expr_eval(expr, &value))
		return 0;
	tr_number_format(value, out, cap);
	return 1;
}
