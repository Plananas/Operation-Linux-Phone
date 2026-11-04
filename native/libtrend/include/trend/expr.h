/* Arithmetic expressions: + - * / ( ) on decimal numbers. Nothing else is accepted. */
#ifndef TREND_EXPR_H
#define TREND_EXPR_H

#include <stddef.h>

/* Evaluate expr. Returns 1 and sets *value, or returns 0 for a syntax error or division by zero. */
int tr_expr_eval(const char *expr, double *value);

/* Format a value for display: whole numbers below 1e15 in full, anything else to 10 significant
 * digits. Writes at most cap bytes, including the terminator. */
void tr_number_format(double value, char *out, size_t cap);

/* tr_expr_eval followed by tr_number_format. Returns 0 and leaves out empty on failure. */
int tr_expr_result(const char *expr, char *out, size_t cap);

#endif
