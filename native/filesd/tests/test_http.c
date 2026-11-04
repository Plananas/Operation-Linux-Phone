/* Unit tests for the byte-level parts of filesd. Run with: make test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "http.h"

static int checks, failures;

#define CHECK(cond) do { \
	checks++; \
	if (!(cond)) { \
		failures++; \
		printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
	} \
} while (0)

static int parse(const char *text, http_req *req, char *buf, size_t cap)
{
	snprintf(buf, cap, "%s", text);
	return http_parse_head(buf, req);
}

static void test_head(void)
{
	char b[512];
	http_req r;
	CHECK(http_head_end("GET / HTTP/1.1\r\n\r\nbody", 22) == 18);
	CHECK(http_head_end("GET / HTTP/1.1\r\n", 16) == -1);

	CHECK(parse("PUT /a/b?x=1 HTTP/1.1\r\nCONTENT-length: 42 \r\nCookie: a=b\r\nX-Trend: 1\r\nRange:bytes=1-2\r\n", &r, b, sizeof(b)) == 0);
	CHECK(!strcmp(r.method, "PUT"));
	CHECK(!strcmp(r.target, "/a/b"));
	CHECK(r.content_length == 42);
	CHECK(!strcmp(r.cookie, "a=b"));
	CHECK(!strcmp(r.range, "bytes=1-2"));
	CHECK(r.same_origin_marker == 1);

	CHECK(parse("GET / HTTP/1.1\r\n", &r, b, sizeof(b)) == 0);
	CHECK(r.content_length == -1);
	CHECK(r.same_origin_marker == 0);

	static const char *const BAD[] = {
		"", "GET\r\n", "GET /\r\n", "GET / HTTP/2\r\n", "GET x HTTP/1.1\r\n", "G T / HTTP/1.1\r\n",
		"GET / HTTP/1.1\r\nno colon\r\n", "GET / HTTP/1.1\r\n: empty\r\n",
		"GET / HTTP/1.1\r\nA: 1\r\n folded\r\n",
		"PUT / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n",
		"PUT / HTTP/1.1\r\nContent-Length: 1\r\nContent-Length: 2\r\n",
		"PUT / HTTP/1.1\r\nContent-Length: -1\r\n",
		"PUT / HTTP/1.1\r\nContent-Length: 1x\r\n",
		"PUT / HTTP/1.1\r\nContent-Length: 99999999999999999999\r\n",
	};
	for (size_t i = 0; i < sizeof(BAD) / sizeof(BAD[0]); i++)
		CHECK(parse(BAD[i], &r, b, sizeof(b)) == -1);
}

static void test_decode(void)
{
	char out[16];
	CHECK(http_decode("a%20b", 5, out, sizeof(out)) == 3 && !strcmp(out, "a b"));
	CHECK(http_decode("%2e%2E", 6, out, sizeof(out)) == 2 && !strcmp(out, ".."));
	CHECK(http_decode("abc", 2, out, sizeof(out)) == 2 && !strcmp(out, "ab"));
	CHECK(http_decode("%", 1, out, sizeof(out)) == -1);
	CHECK(http_decode("%2", 2, out, sizeof(out)) == -1);
	CHECK(http_decode("%2", 1, out, sizeof(out)) == -1);
	CHECK(http_decode("%zz", 3, out, sizeof(out)) == -1);
	CHECK(http_decode("%00", 3, out, sizeof(out)) == -1);
	CHECK(http_decode("abcd", 4, out, 4) == -1);
	CHECK(http_decode("abc", 3, out, 4) == 3);
}

static void test_names(void)
{
	char long_ok[256], too_long[257];
	memset(long_ok, 'a', 255);
	long_ok[255] = '\0';
	memset(too_long, 'a', 256);
	too_long[256] = '\0';

	static const char *const GOOD[] = { "a", "song.mp3", "a b (1).flac", "caf\xc3\xa9", "\xe6\x97\xa5\xe6\x9c\xac", "\xf0\x9f\x8e\xb5" };
	for (size_t i = 0; i < sizeof(GOOD) / sizeof(GOOD[0]); i++)
		CHECK(fs_name_ok(GOOD[i]));
	CHECK(fs_name_ok(long_ok));

	static const char *const BAD[] = {
		"", ".", "..", ".hidden", "a/b", "/", "a\\b", "a\nb", "a\rb", "a\tb", "\x7f",
		"\xff", "\xc0\xaf", "\xe0\x80\xaf", "\xed\xa0\x80", "\xf4\x90\x80\x80", "\xc3",
	};
	for (size_t i = 0; i < sizeof(BAD) / sizeof(BAD[0]); i++)
		CHECK(!fs_name_ok(BAD[i]));
	CHECK(!fs_name_ok(too_long));
}

static void test_range(void)
{
	int64_t a = -1, b = -1;
	CHECK(http_parse_range("bytes=0-9", 100, &a, &b) == 1 && a == 0 && b == 9);
	CHECK(http_parse_range("bytes=90-", 100, &a, &b) == 1 && a == 90 && b == 99);
	CHECK(http_parse_range("bytes=90-500", 100, &a, &b) == 1 && a == 90 && b == 99);
	CHECK(http_parse_range("bytes=-10", 100, &a, &b) == 1 && a == 90 && b == 99);
	CHECK(http_parse_range("bytes=-500", 100, &a, &b) == 1 && a == 0 && b == 99);
	CHECK(http_parse_range("bytes=100-", 100, &a, &b) == -1);
	CHECK(http_parse_range("bytes=5-2", 100, &a, &b) == -1);
	CHECK(http_parse_range("bytes=-0", 100, &a, &b) == -1);
	CHECK(http_parse_range("bytes=0-", 0, &a, &b) == -1);
	CHECK(http_parse_range("bytes=0-1,3-4", 100, &a, &b) == 0);
	CHECK(http_parse_range("lines=0-1", 100, &a, &b) == 0);
	CHECK(http_parse_range("bytes=x-1", 100, &a, &b) == 0);
	CHECK(http_parse_range("bytes=99999999999999999999-", 100, &a, &b) == 0);
}

static void test_cookie(void)
{
	char v[8];
	CHECK(http_cookie_value("a=1; b=22; c=3", "b", v, sizeof(v)) == 0 && !strcmp(v, "22"));
	CHECK(http_cookie_value("a=1", "a", v, sizeof(v)) == 0 && !strcmp(v, "1"));
	CHECK(http_cookie_value("ab=1", "a", v, sizeof(v)) == -1);
	CHECK(http_cookie_value("", "a", v, sizeof(v)) == -1);
	CHECK(http_cookie_value("a=12345678", "a", v, sizeof(v)) == -1);
}

static void test_escape(void)
{
	char o[32];
	CHECK(json_escape("a\"b\\c", o, sizeof(o)) == 7 && !strcmp(o, "a\\\"b\\\\c"));
	CHECK(json_escape("\x01", o, sizeof(o)) == 6 && !strcmp(o, "\\u0001"));
	CHECK(json_escape("abcd", o, 4) == -1);
	CHECK(http_encode_attr("a b;\"\xc3\xa9.mp3", o, sizeof(o)) > 0 && !strcmp(o, "a%20b%3B%22%C3%A9.mp3"));
	CHECK(http_encode_attr("  ", o, 6) == -1);
}

int main(void)
{
	test_head();
	test_decode();
	test_names();
	test_range();
	test_cookie();
	test_escape();
	printf("%d checks, %d failures\n", checks, failures);
	return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
