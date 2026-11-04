# libtrendplay: the music player. Needs alsa-lib-dev and libsndfile-dev, so it's built on the phone.
#   make            build libtrendplay.so
#   make test       build and run the tests, silently, against ALSA's null device
#   make clean
CC      ?= gcc
LIBTREND := ../libtrend
WARN    := -Wall -Wextra -Wshadow
CFLAGS  := -std=gnu11 -O2 -fPIC -I. -I$(LIBTREND)/include $(WARN)
SRC     := player.c $(LIBTREND)/src/apps/music/music_text.c
LIBS    := -lsndfile -lasound -lpthread -lm

ifneq (,$(findstring armv7,$(shell uname -m)))
CFLAGS  += -mcpu=cortex-a7 -mfpu=neon-vfpv4
endif

libtrendplay.so: $(SRC) player.h
	$(CC) $(CFLAGS) -shared -o $@ $(SRC) $(LIBS)

test: tests/test_player.c $(SRC) player.h
	$(CC) $(CFLAGS) -g -o test_player tests/test_player.c $(SRC) $(LIBS)
	./test_player

clean:
	rm -f libtrendplay.so test_player

.PHONY: test clean
