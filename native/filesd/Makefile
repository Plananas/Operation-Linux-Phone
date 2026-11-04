# filesd: the web server behind the Files app.
#   make            build filesd for this machine
#   make test       unit tests and a real server run, under the address and UB sanitizers
#   make clean
CC      ?= gcc
WARN    := -Wall -Wextra -Wshadow -Wconversion -Wno-sign-conversion -Werror
CFLAGS  := -std=gnu11 -O2 -fstack-protector-strong -D_FORTIFY_SOURCE=2 $(WARN)
SRC     := filesd.c http.c
SAN     := -std=gnu11 -O1 -g $(WARN) -fsanitize=address,undefined -fno-sanitize-recover=all

filesd: $(SRC) http.h
	$(CC) $(CFLAGS) -o $@ $(SRC) -lpthread

test: tests/test_http.c tests/test_server.py $(SRC) http.h
	$(CC) $(SAN) -I. -o test_http tests/test_http.c http.c
	./test_http
	$(CC) $(SAN) -o filesd-test $(SRC) -lpthread
	python3 tests/test_server.py ./filesd-test

clean:
	rm -f filesd filesd-test test_http

.PHONY: test clean
