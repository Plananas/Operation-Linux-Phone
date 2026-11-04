# webd: the Web app's connection to the internet, and its chat agent.
#   make            build webd for this machine (needs OpenSSL and stb headers: the phone has them)
#   make test       unit tests of the parts that only look at bytes, under the address and UB sanitizers
#   make clean
CC      ?= gcc
WARN    := -Wall -Wextra -Wshadow -Wconversion -Wno-sign-conversion -Werror
CFLAGS  := -std=gnu11 -O2 -fstack-protector-strong -D_FORTIFY_SOURCE=2 -I../libtrend/include $(WARN)
PURE    := doc.c url.c html.c json.c ascii.c
SRC     := $(PURE) net.c fetch.c wire.c agent.c webd.c
SAN     := -std=gnu11 -O1 -g -I. -I../libtrend/include $(WARN) -fsanitize=address,undefined -fno-sanitize-recover=all

webd: $(SRC) $(wildcard *.h)
	$(CC) $(CFLAGS) -o $@ $(SRC) -lssl -lcrypto -lm

test: tests/test_webd.c $(PURE) $(wildcard *.h)
	$(CC) $(SAN) -o test_webd tests/test_webd.c $(PURE) -lm
	./test_webd

clean:
	rm -f webd test_webd

.PHONY: test clean
