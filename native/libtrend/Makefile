# libtrend: the C core of TREND OS.
#   make            build libtrend.so for this machine (Cortex-A7 + NEON on the phone)
#   make test       build and run the unit tests under the address and UB sanitizers
#   make clean
CC      ?= gcc
WARN    := -Wall -Wextra -Wshadow -Wconversion -Wno-sign-conversion -Werror
CFLAGS  := -std=gnu11 -O3 -ftree-vectorize -fPIC -Iinclude $(WARN)
SRC     := $(wildcard src/*.c src/apps/*.c)
HDR     := $(wildcard include/trend/*.h include/trend/apps/*.h src/apps/*.h)

ifneq (,$(findstring armv7,$(shell uname -m)))
CFLAGS  += -mcpu=cortex-a7 -mfpu=neon-vfpv4
endif

libtrend.so: $(SRC) $(HDR)
	$(CC) $(CFLAGS) -shared -o $@ $(SRC) -lm

test: tests/test_libtrend.c $(SRC) $(HDR)
	$(CC) -std=gnu11 -O1 -g -Iinclude $(WARN) -fsanitize=address,undefined -fno-sanitize-recover=all \
		-o test_libtrend tests/test_libtrend.c $(SRC) -lm
	./test_libtrend

clean:
	rm -f libtrend.so test_libtrend

.PHONY: test clean
