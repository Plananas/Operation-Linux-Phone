/* Tests for the player, against ALSA's null device, so they're silent and run faster than real time.
 * It needs libsndfile and ALSA, so run it on the phone: make test */
#include <math.h>
#include <sndfile.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "player.h"

static int checks, failures;

#define CHECK(cond) do { \
	checks++; \
	if (!(cond)) { \
		failures++; \
		printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
	} \
} while (0)

static void write_tone(const char *path, int format, int channels, int rate, int seconds)
{
	SF_INFO info = { .samplerate = rate, .channels = channels, .format = format };
	SNDFILE *f = sf_open(path, SFM_WRITE, &info);
	if (!f) {
		printf("can't write %s: %s\n", path, sf_strerror(NULL));
		exit(EXIT_FAILURE);
	}
	int16_t frame[2];
	for (int i = 0; i < rate * seconds; i++) {
		frame[0] = frame[1] = (int16_t)(8000.0 * sin(i * 0.05));
		sf_writef_short(f, frame, 1);
	}
	sf_close(f);
}

static void sleep_ms(int ms)
{
	struct timespec t = { ms / 1000, (long)(ms % 1000) * 1000000L };
	nanosleep(&t, NULL);
}

typedef int (*condition)(const tr_music_status *);

/* Wait for the player to reach a condition; returns whether it did. */
static int wait_for(tr_player *p, condition holds, tr_music_status *st)
{
	for (int i = 0; i < 500; i++) {
		tr_player_status(p, st);
		if (holds(st))
			return 1;
		sleep_ms(10);
	}
	return 0;
}

static int stopped(const tr_music_status *s) { return s->state == TR_PLAYER_STOPPED; }
static int paused(const tr_music_status *s) { return s->state == TR_PLAYER_PAUSED; }
static int found_tracks(const tr_music_status *s) { return s->n_tracks > 0; }

static void cmd(tr_player *p, int kind, int arg)
{
	tr_player_command(p, (tr_music_cmd){ kind, arg });
}

/* Audio past full scale must clip, not wrap round. A float file holds such samples exactly, the way
 * a loud MP3 decodes. FLAC goes through here too, to show that format plays. */
static void test_over_full_scale(void)
{
	char dir[] = "/tmp/test-player-XXXXXX", path[128], clean[160];
	if (!mkdtemp(dir))
		exit(EXIT_FAILURE);
	snprintf(path, sizeof(path), "%s/a.flac", dir);
	write_tone(path, SF_FORMAT_FLAC | SF_FORMAT_PCM_16, 2, 44100, 1);
	snprintf(path, sizeof(path), "%s/b.wav", dir);
	SF_INFO info = { .samplerate = 44100, .channels = 2, .format = SF_FORMAT_WAV | SF_FORMAT_FLOAT };
	SNDFILE *f = sf_open(path, SFM_WRITE, &info);
	const float loud[2] = { 1.5f, 1.5f };
	for (int i = 0; i < 44100 * 30; i++)
		sf_writef_float(f, loud, 1);
	sf_close(f);

	tr_player *p = tr_player_new(dir, "null");
	tr_music_status st;
	CHECK(wait_for(p, found_tracks, &st));
	cmd(p, TR_CMD_PLAY_TRACK, 0);
	for (int i = 0; i < 500; i++) {                 /* the FLAC runs out, and on to the loud file */
		tr_player_status(p, &st);
		if (st.track == 1 && st.position > 0.1)
			break;
		sleep_ms(2);
	}
	CHECK(st.track == 1);
	cmd(p, TR_CMD_RELEASE, 0);
	tr_player_status(p, &st);
	CHECK(st.state == TR_PLAYER_PAUSED);
	int lowest = 32767;
	for (int i = 0; i < TR_MUSIC_SCOPE; i++)
		if (st.scope[i] < lowest)
			lowest = st.scope[i];
	CHECK(lowest > 32000);
	tr_player_free(p);
	snprintf(clean, sizeof(clean), "rm -rf %s", dir);
	if (system(clean) != 0)
		exit(EXIT_FAILURE);
}

/* A tone in a new file, making its folder. */
static void add_tone(const char *dir, const char *folder, const char *name)
{
	char path[700];
	snprintf(path, sizeof(path), "%s/%s", dir, folder);
	mkdir(path, 0755);
	snprintf(path, sizeof(path), "%s/%s/%s", dir, folder, name);
	write_tone(path, SF_FORMAT_WAV | SF_FORMAT_PCM_16, 2, 44100, 1);
}

/* Folders are playlists: their tracks stay together, and playing stays inside one. */
static void test_folders(void)
{
	char dir[] = "/tmp/test-player-XXXXXX", clean[160], long_folder[121], long_name[185];
	if (!mkdtemp(dir))
		exit(EXIT_FAILURE);
	add_tone(dir, ".", "z_loose.wav");
	add_tone(dir, "band", "one.wav");
	add_tone(dir, "band", "two.wav");
	add_tone(dir, "band", "y_last.wav");
	add_tone(dir, "band/m_live", "inner.wav");         /* sorts between band's own tracks by full path */
	add_tone(dir, "Band", "other.wav");                /* differs only by case */
	add_tone(dir, "a_first", "x.wav");
	mkdir(strcat(strcpy(clean, dir), "/empty"), 0755);
	memset(long_folder, 'f', 120);                     /* together, longer than a single name can be */
	long_folder[120] = '\0';
	memset(long_name, 'n', 180);
	strcpy(long_name + 180, ".wav");
	add_tone(dir, long_folder, long_name);

	tr_player *p = tr_player_new(dir, "null");
	tr_music_status st;
	static tr_music_library lib;
	CHECK(wait_for(p, found_tracks, &st));
	tr_player_library(p, &lib);
	CHECK(lib.n == 8);
	CHECK(lib.n_folders == 6);
	CHECK(lib.folders[0].first == 0 && lib.folders[0].n == 1 && lib.folders[0].name[0] == '\0');
	CHECK(strcmp(lib.names[0], "z loose") == 0);
	CHECK(strcmp(lib.folders[1].name, "a first") == 0 && lib.folders[1].first == 1 && lib.folders[1].n == 1);
	const tr_music_folder *upper = &lib.folders[2], *lower = &lib.folders[3], *nested = &lib.folders[4];
	CHECK(strcmp(upper->name, "Band") == 0 && upper->first == 2 && upper->n == 1);
	CHECK(strcmp(lower->name, "band") == 0 && lower->first == 3 && lower->n == 3);
	CHECK(strcmp(lib.names[3], "one") == 0 && strcmp(lib.names[4], "two") == 0 && strcmp(lib.names[5], "y last") == 0);
	CHECK(strcmp(nested->name, "band/m live") == 0 && nested->first == 6 && nested->n == 1);

	/* Playing runs to the end of the folder and stops there, without the next folder's tracks. */
	cmd(p, TR_CMD_PLAY_TRACK, 3);
	int last = -1;
	for (int i = 0; i < 3000; i++) {
		tr_player_status(p, &st);
		if (st.track > last)
			last = st.track;
		if (st.state == TR_PLAYER_STOPPED && last >= 0)
			break;
		sleep_ms(1);
	}
	CHECK(last == 5);
	CHECK(st.state == TR_PLAYER_STOPPED);

	/* Next at the folder's end and previous at its start stay put. */
	cmd(p, TR_CMD_PLAY_TRACK, 5);
	cmd(p, TR_CMD_RELEASE, 0);
	tr_player_status(p, &st);
	CHECK(st.state == TR_PLAYER_PAUSED && st.track == 5);
	cmd(p, TR_CMD_NEXT, 0);
	sleep_ms(50);
	tr_player_status(p, &st);
	CHECK(st.state == TR_PLAYER_PAUSED && st.track == 5);
	cmd(p, TR_CMD_PLAY_TRACK, 3);
	cmd(p, TR_CMD_RELEASE, 0);
	cmd(p, TR_CMD_PREV, 0);
	sleep_ms(50);
	tr_player_status(p, &st);
	CHECK(st.state == TR_PLAYER_PAUSED && st.track == 3);

	/* A rescan keeps the playing track's place when the folders around it change. */
	add_tone(dir, "a_first", "y.wav");
	cmd(p, TR_CMD_RESCAN, 0);
	sleep_ms(100);
	tr_player_status(p, &st);
	tr_player_library(p, &lib);
	CHECK(lib.n == 9 && st.track == 4 && st.state == TR_PLAYER_PAUSED);

	tr_player_free(p);
	snprintf(clean, sizeof(clean), "rm -rf %s", dir);
	if (system(clean) != 0)
		exit(EXIT_FAILURE);
}

int main(void)
{
	test_over_full_scale();
	test_folders();

	char dir[] = "/tmp/test-player-XXXXXX", path[128];
	if (!mkdtemp(dir))
		return EXIT_FAILURE;

	/* A mono WAV, a nested stereo MP3 at another rate, a non-audio file and a corrupt "MP3". */
	snprintf(path, sizeof(path), "%s/B_second.wav", dir);
	write_tone(path, SF_FORMAT_WAV | SF_FORMAT_PCM_16, 1, 22050, 3);
	snprintf(path, sizeof(path), "%s/album", dir);
	mkdir(path, 0755);
	snprintf(path, sizeof(path), "%s/album/first.mp3", dir);
	write_tone(path, SF_FORMAT_MPEG | SF_FORMAT_MPEG_LAYER_III, 2, 44100, 3);
	snprintf(path, sizeof(path), "%s/notes.txt", dir);
	fclose(fopen(path, "w"));
	snprintf(path, sizeof(path), "%s/C_broken.mp3", dir);
	FILE *junk = fopen(path, "w");
	fputs("this isn't audio", junk);
	fclose(junk);

	tr_player *p = tr_player_new(dir, "null");
	tr_music_status st;
	static tr_music_library lib;
	CHECK(p != NULL);
	CHECK(wait_for(p, found_tracks, &st));

	/* The music folder's own tracks, then each folder's, without the text file. */
	tr_player_library(p, &lib);
	CHECK(lib.n == 3);
	CHECK(strcmp(lib.names[0], "B second") == 0);
	CHECK(strcmp(lib.names[1], "C broken") == 0);
	CHECK(strcmp(lib.names[2], "first") == 0);
	const unsigned version = lib.version;
	tr_player_library(p, &lib);
	CHECK(lib.version == version);
	CHECK(st.state == TR_PLAYER_STOPPED && st.track == -1);

	/* Pausing and releasing while stopped does nothing, and comes back promptly. */
	cmd(p, TR_CMD_RELEASE, 0);
	tr_player_status(p, &st);
	CHECK(st.state == TR_PLAYER_STOPPED);

	/* Play the WAV. The null device takes audio as fast as we decode it, so it soon runs out and
	 * moves on to the broken file, and stops, because the next track is in a folder. */
	cmd(p, TR_CMD_PLAY_TRACK, 0);
	sleep_ms(50);
	CHECK(wait_for(p, stopped, &st));
	CHECK(st.title[0] == '\0' && st.position == 0.0 && st.track == -1);
	CHECK(strcmp(st.error, "Can't read this music") == 0);

	CHECK(!tr_player_is_playing(p));

	/* Volume is set to a level, and stays in range. */
	cmd(p, TR_CMD_VOLUME, 7);
	tr_player_status(p, &st);
	CHECK(st.volume == 7);
	cmd(p, TR_CMD_VOLUME, TR_MUSIC_VOLUME_MAX + 40);
	tr_player_status(p, &st);
	CHECK(st.volume == TR_MUSIC_VOLUME_MAX);
	cmd(p, TR_CMD_VOLUME, -40);
	tr_player_status(p, &st);
	CHECK(st.volume == 0);

	/* A command for a track that doesn't exist is ignored. */
	cmd(p, TR_CMD_PLAY_TRACK, 99);
	sleep_ms(50);
	tr_player_status(p, &st);
	CHECK(st.state == TR_PLAYER_STOPPED);

	/* Release beats a play sent just before it, and toggling resumes from the same place. */
	cmd(p, TR_CMD_PLAY_TRACK, 0);
	cmd(p, TR_CMD_RELEASE, 0);
	CHECK(wait_for(p, paused, &st));
	const double held = st.position;
	sleep_ms(50);
	tr_player_status(p, &st);
	CHECK(st.position == held);
	CHECK(st.track == 0);
	CHECK(strcmp(st.title, "B second") == 0);
	CHECK(st.duration > 2.9 && st.duration < 3.1);

	/* Seeking while paused moves the position, and survives the file's real length. */
	cmd(p, TR_CMD_SEEK, 500);
	sleep_ms(50);
	tr_player_status(p, &st);
	CHECK(st.state == TR_PLAYER_PAUSED);
	CHECK(st.position > 1.4 && st.position < 1.6);

	cmd(p, TR_CMD_TOGGLE, 0);
	sleep_ms(50);
	CHECK(wait_for(p, stopped, &st));

	/* A new file shows up on a rescan, and the list keeps its order. */
	snprintf(path, sizeof(path), "%s/A_new.wav", dir);
	write_tone(path, SF_FORMAT_WAV | SF_FORMAT_PCM_16, 2, 44100, 1);
	cmd(p, TR_CMD_RESCAN, 0);
	sleep_ms(100);
	tr_player_library(p, &lib);
	CHECK(lib.n == 4);
	CHECK(lib.version != version);
	CHECK(strcmp(lib.names[0], "A new") == 0);
	CHECK(strcmp(lib.names[1], "B second") == 0);

	tr_player_free(p);
	char clean[160];
	snprintf(clean, sizeof(clean), "rm -rf %s", dir);
	if (system(clean) != 0)
		return EXIT_FAILURE;
	printf("%d checks, %d failures\n", checks, failures);
	return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
