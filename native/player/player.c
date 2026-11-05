/* The music player's thread: scanning, decoding (libsndfile), output (ALSA). See player.h.
 *
 * Commands only leave requests in the struct and wake the thread. The thread alone touches the file,
 * the audio device and the paths, so slow work never holds the lock that the screen reads through.
 */
#define _GNU_SOURCE
#include <alsa/asoundlib.h>
#include <dirent.h>
#include <errno.h>
#include <pthread.h>
#include <sndfile.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <time.h>

#include "player.h"

enum {
	PATH_CAP = 256,
	BLOCK_FRAMES = 1024,
	MAX_CHANNELS = 8,
	SCOPE_DECIMATE = 4,
	LATENCY_US = 300000,
	THREAD_STACK = 512 * 1024,     /* musl's default is too small for the decoders */
	IDLE_WAIT_MS = 200,
	MAX_SCAN_DEPTH = 6,
	DEFAULT_VOLUME = 10,
};

#define RELEASE_TIMEOUT_S 1
#define HEADPHONE_CHECK_S 1.0
#define BLUETOOTH_CHECK_S 5.0
#define RESTART_AFTER_S 3.0            /* "previous" within this time goes to the previous track */
#define HEADPHONE_STATE "/sys/class/switch/h2w/state"
#define DEVICE_PHONE "plughw:CARD=sprdphone,DEV=0"
#define ROUTE_SPEAKER "/usr/local/sbin/audio-headphones off; /usr/local/sbin/audio-speaker on"
#define ROUTE_HEADPHONES "/usr/local/sbin/audio-speaker off; /usr/local/sbin/audio-headphones on"

typedef char track_path[PATH_CAP];

struct tr_player {
	pthread_t thread;
	pthread_mutex_t lock;
	pthread_cond_t wake, released;

	/* Requests: set under the lock, taken by the thread. */
	int want_track, want_seek, want_toggle, want_next, want_prev, want_rescan, quit;
	unsigned pauses_asked, pauses_done;

	/* Published: read and written under the lock. */
	tr_music_status status;
	tr_music_library library;

	/* The thread's own. */
	char dir[PATH_CAP], fixed_device[64];
	track_path *paths;
	int n_paths;
	SNDFILE *file;
	SF_INFO info;
	snd_pcm_t *pcm;
	unsigned pcm_rate;
	sf_count_t frame;
	int output;                    /* what the routing is set to */
	char bt_mac[32];
	double headphone_check_at, bluetooth_check_at;
};

/* The requests taken in one pass of the loop. */
typedef struct {
	int track, seek, toggle, next, prev, rescan, quit;
	unsigned pauses;
} requests;

static double monotonic(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}

static void publish_error(tr_player *p, const char *message)
{
	pthread_mutex_lock(&p->lock);
	snprintf(p->status.error, sizeof(p->status.error), "%s", message);
	pthread_mutex_unlock(&p->lock);
}

static void publish_state(tr_player *p, int state)
{
	pthread_mutex_lock(&p->lock);
	p->status.state = state;
	pthread_mutex_unlock(&p->lock);
}

/* ---- finding the music ---- */

static int is_audio_file(const char *name)
{
	static const char *const EXTENSIONS[] = { ".mp3", ".flac", ".ogg", ".oga", ".opus", ".wav" };
	const char *dot = strrchr(name, '.');
	if (!dot)
		return 0;
	for (size_t i = 0; i < sizeof(EXTENSIONS) / sizeof(EXTENSIONS[0]); i++)
		if (strcasecmp(dot, EXTENSIONS[i]) == 0)
			return 1;
	return 0;
}

static int compare_paths(const void *a, const void *b)
{
	return strcasecmp((const char *)a, (const char *)b);
}

static int scan_dir(const char *dir, track_path *out, int n, int depth)
{
	DIR *d = opendir(dir);
	if (!d)
		return n;
	const struct dirent *e;
	while ((e = readdir(d)) && n < TR_MUSIC_MAX_TRACKS) {
		char path[PATH_CAP];
		struct stat st;
		if (e->d_name[0] == '.')
			continue;
		const int len = snprintf(path, sizeof(path), "%s/%s", dir, e->d_name);
		if (len < 0 || len >= PATH_CAP || stat(path, &st) != 0)
			continue;
		if (S_ISDIR(st.st_mode)) {
			if (depth < MAX_SCAN_DEPTH)
				n = scan_dir(path, out, n, depth + 1);
		} else if (S_ISREG(st.st_mode) && is_audio_file(e->d_name)) {
			memcpy(out[n++], path, (size_t)len + 1);
		}
	}
	closedir(d);
	return n;
}

/* Rebuild the list, keeping the playing track's place in it. */
static void rescan(tr_player *p, int current)
{
	char playing[PATH_CAP] = "";
	if (current >= 0 && current < p->n_paths)
		snprintf(playing, sizeof(playing), "%s", p->paths[current]);
	p->n_paths = scan_dir(p->dir, p->paths, 0, 0);
	qsort(p->paths, (size_t)p->n_paths, sizeof(track_path), compare_paths);

	pthread_mutex_lock(&p->lock);
	p->library.n = p->status.n_tracks = p->n_paths;
	p->status.track = -1;
	for (int i = 0; i < p->n_paths; i++) {
		tr_music_display_name(p->paths[i], p->library.names[i], TR_MUSIC_NAME);
		if (playing[0] && strcmp(p->paths[i], playing) == 0)
			p->status.track = i;
	}
	p->library.version++;
	pthread_mutex_unlock(&p->lock);
}

/* ---- choosing an output ---- */

static int headphones_in(void)
{
	FILE *f = fopen(HEADPHONE_STATE, "r");
	int state = 0;
	if (f) {
		if (fscanf(f, "%d", &state) != 1)
			state = 0;
		fclose(f);
	}
	return state != 0;
}

/* The address of a connected Bluetooth speaker or headset, from BlueALSA's list of devices:
 * /org/bluealsa/hci0/dev_XX_XX_XX_XX_XX_XX/a2dpsrc/sink */
static void find_bluetooth(char *mac, size_t cap)
{
	char line[256];
	mac[0] = '\0';
	FILE *f = popen("bluealsa-cli -q list-pcms 2>/dev/null", "r");
	if (!f)
		return;
	while (fgets(line, sizeof(line), f)) {
		const char *dev = strstr(line, "/dev_");
		if (dev && strstr(line, "/a2dpsrc/sink") && !mac[0]) {
			snprintf(mac, cap, "%.17s", dev + 5);
			for (char *c = mac; *c; c++)
				if (*c == '_')
					*c = ':';
		}
	}
	pclose(f);
}

static int best_output(const tr_player *p)
{
	return p->bt_mac[0] ? TR_OUTPUT_BLUETOOTH : headphones_in() ? TR_OUTPUT_HEADPHONES : TR_OUTPUT_SPEAKER;
}

static void route_to(int output)
{
	if (output == TR_OUTPUT_SPEAKER && system(ROUTE_SPEAKER) != 0)
		fprintf(stderr, "player: speaker routing failed\n");
	if (output == TR_OUTPUT_HEADPHONES && system(ROUTE_HEADPHONES) != 0)
		fprintf(stderr, "player: headphone routing failed\n");
}

/* ---- the audio device ---- */

static void close_pcm(tr_player *p, int drain)
{
	if (!p->pcm)
		return;
	if (drain)
		snd_pcm_drain(p->pcm);
	else
		snd_pcm_drop(p->pcm);
	snd_pcm_close(p->pcm);
	p->pcm = NULL;
}

static int open_pcm(tr_player *p, unsigned rate)
{
	char device[96];
	int err;
	if (p->fixed_device[0]) {
		snprintf(device, sizeof(device), "%s", p->fixed_device);
	} else {
		find_bluetooth(p->bt_mac, sizeof(p->bt_mac));
		p->bluetooth_check_at = monotonic() + BLUETOOTH_CHECK_S;
		p->output = best_output(p);
		route_to(p->output);
		if (p->output == TR_OUTPUT_BLUETOOTH)
			snprintf(device, sizeof(device), "trendbt:DEV=%s", p->bt_mac);
		else
			snprintf(device, sizeof(device), "%s", DEVICE_PHONE);
	}
	/* Non-blocking open: if an alarm holds the device, fail rather than wait for it. */
	err = snd_pcm_open(&p->pcm, device, SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);
	if (err == 0)
		err = snd_pcm_nonblock(p->pcm, 0);
	if (err == 0)
		err = snd_pcm_set_params(p->pcm, SND_PCM_FORMAT_S16_LE, SND_PCM_ACCESS_RW_INTERLEAVED, 2, rate, 1, LATENCY_US);
	if (err < 0) {
		if (p->pcm)
			snd_pcm_close(p->pcm);
		p->pcm = NULL;
		publish_error(p, err == -EBUSY ? "Audio is busy: try again" : "Can't open the audio output");
		return 0;
	}
	p->pcm_rate = rate;
	pthread_mutex_lock(&p->lock);
	p->status.output = p->output;
	p->status.error[0] = '\0';
	pthread_mutex_unlock(&p->lock);
	return 1;
}

/* ---- tracks ---- */

static void close_track(tr_player *p)
{
	if (p->file)
		sf_close(p->file);
	p->file = NULL;
	p->frame = 0;
}

static void publish_tags(tr_player *p, int index)
{
	char title[TR_MUSIC_NAME], artist[TR_MUSIC_NAME] = "";
	const char *tag = sf_get_string(p->file, SF_STR_TITLE);
	if (tag && tag[0])
		tr_music_latin1(tag, title, sizeof(title));
	else
		tr_music_display_name(p->paths[index], title, sizeof(title));
	tag = sf_get_string(p->file, SF_STR_ARTIST);
	if (tag)
		tr_music_latin1(tag, artist, sizeof(artist));

	pthread_mutex_lock(&p->lock);
	p->status.track = index;
	p->status.position = 0.0;
	p->status.duration = p->info.samplerate > 0 ? (double)p->info.frames / p->info.samplerate : 0.0;
	memcpy(p->status.title, title, sizeof(title));
	memcpy(p->status.artist, artist, sizeof(artist));
	p->status.error[0] = '\0';
	pthread_mutex_unlock(&p->lock);
}

/* Open the track at index, or the next one that will open. Returns whether one did. */
static int open_track(tr_player *p, int index)
{
	close_track(p);
	for (int i = index; i < p->n_paths; i++) {
		memset(&p->info, 0, sizeof(p->info));
		p->file = sf_open(p->paths[i], SFM_READ, &p->info);
		if (p->file && p->info.channels <= MAX_CHANNELS) {
			publish_tags(p, i);
			return 1;
		}
		if (p->file)
			sf_close(p->file);
		p->file = NULL;
	}
	publish_error(p, "Can't read this music");
	return 0;
}

static void stop_playing(tr_player *p, int drain)
{
	close_pcm(p, drain);
	close_track(p);
	pthread_mutex_lock(&p->lock);
	p->status.state = TR_PLAYER_STOPPED;
	p->status.track = -1;
	p->status.position = 0.0;
	p->status.duration = 0.0;
	p->status.title[0] = p->status.artist[0] = '\0';
	memset(p->status.scope, 0, sizeof(p->status.scope));
	pthread_mutex_unlock(&p->lock);
}

/* Start the track at index playing. The device stays open between tracks of the same sample rate,
 * so albums run on without a gap. */
static void play_track(tr_player *p, int index)
{
	if (p->n_paths == 0 || !open_track(p, index)) {
		stop_playing(p, 0);
		return;
	}
	const unsigned rate = (unsigned)p->info.samplerate;
	if (p->pcm && p->pcm_rate != rate)
		close_pcm(p, 1);
	if (!p->pcm && !open_pcm(p, rate)) {
		publish_state(p, TR_PLAYER_PAUSED);
		return;
	}
	publish_state(p, TR_PLAYER_PLAYING);
}

static void pause_playing(tr_player *p)
{
	close_pcm(p, 0);                       /* an alarm or the radio can have the device now */
	publish_state(p, TR_PLAYER_PAUSED);
}

static void toggle(tr_player *p, int state, int track)
{
	if (state == TR_PLAYER_PLAYING) {
		pause_playing(p);
	} else if (state == TR_PLAYER_PAUSED && p->file) {
		if (open_pcm(p, (unsigned)p->info.samplerate))
			publish_state(p, TR_PLAYER_PLAYING);
	} else {
		play_track(p, track >= 0 ? track : 0);
	}
}

static void seek_to(tr_player *p, int thousandths)
{
	if (!p->file || p->info.frames <= 0)
		return;
	const sf_count_t target = p->info.frames / 1000 * tr_clamp(thousandths, 0, 1000);
	const sf_count_t at = sf_seek(p->file, target, SEEK_SET);
	if (at >= 0)
		p->frame = at;
	if (p->pcm) {                          /* don't play out what's queued from the old place */
		snd_pcm_drop(p->pcm);
		snd_pcm_prepare(p->pcm);
	}
	pthread_mutex_lock(&p->lock);
	p->status.position = (double)p->frame / p->info.samplerate;
	pthread_mutex_unlock(&p->lock);
}

/* ---- the hot path ---- */

/* We always decode to float and convert here, whatever the file holds. Lossy formats overshoot full
 * scale on loud music, and these samples must clip: wrapped round to the opposite extreme, they're a
 * loud click. libsndfile's own 16-bit reads wrap by default, and don't scale float files at all. */
static inline int16_t to_s16(float x)
{
	const float v = x * 32767.0f;
	return (int16_t)(v > 32767.0f ? 32767.0f : v < -32768.0f ? -32768.0f : v);
}

/* Interleaved source frames down to stereo, at the volume. */
static void to_stereo(int16_t *dst, const float *src, int frames, int channels, float gain)
{
	const int right = channels > 1 ? 1 : 0;
	for (int i = 0; i < frames; i++) {
		dst[i * 2] = to_s16(src[i * channels] * gain);
		dst[i * 2 + 1] = to_s16(src[i * channels + right] * gain);
	}
}

/* The latest stretch of source audio, for the visualiser. It shows the music rather than the
 * volume setting, so it doesn't shrink when the sound is turned down. */
static void take_scope(int16_t *scope, const float *src, int frames, int channels)
{
	const int right = channels > 1 ? 1 : 0;
	const int n = tr_min(TR_MUSIC_SCOPE, frames / SCOPE_DECIMATE);
	for (int i = 0; i < n; i++) {
		const float *f = src + i * SCOPE_DECIMATE * channels;
		scope[i] = to_s16((f[0] + f[right]) / 2.0f);
	}
	for (int i = n; i < TR_MUSIC_SCOPE; i++)
		scope[i] = 0;
}

static float gain_of(int volume)
{
	return (float)(volume * volume) / (float)(TR_MUSIC_VOLUME_MAX * TR_MUSIC_VOLUME_MAX);
}

static void write_block(tr_player *p, const int16_t *stereo, int frames)
{
	int done = 0;
	while (done < frames && p->pcm) {
		snd_pcm_sframes_t n = snd_pcm_writei(p->pcm, stereo + done * 2, (snd_pcm_uframes_t)(frames - done));
		if (n < 0)
			n = snd_pcm_recover(p->pcm, (int)n, 1);
		if (n < 0) {
			publish_error(p, "Audio output stopped");
			pause_playing(p);
			return;
		}
		done += (int)n;
	}
}

static void play_block(tr_player *p, int track)
{
	float source[BLOCK_FRAMES * MAX_CHANNELS];
	int16_t stereo[BLOCK_FRAMES * 2], scope[TR_MUSIC_SCOPE];
	const int frames = (int)sf_readf_float(p->file, source, BLOCK_FRAMES);
	if (frames <= 0) {                     /* the end of the track */
		if (track + 1 < p->n_paths)
			play_track(p, track + 1);
		else
			stop_playing(p, 1);
		return;
	}
	const int channels = p->info.channels;
	take_scope(scope, source, frames, channels);
	p->frame += frames;

	pthread_mutex_lock(&p->lock);
	const float gain = gain_of(p->status.volume);
	p->status.position = (double)p->frame / p->info.samplerate;
	memcpy(p->status.scope, scope, sizeof(scope));
	pthread_mutex_unlock(&p->lock);

	to_stereo(stereo, source, frames, channels, gain);
	write_block(p, stereo, frames);
}

/* While playing, notice outputs coming and going. Losing one pauses, so that unplugging headphones
 * doesn't suddenly play out of the speaker. Gaining one moves the sound there. */
static void check_outputs(tr_player *p)
{
	const double now = monotonic();
	if (p->fixed_device[0] || now < p->headphone_check_at)
		return;
	p->headphone_check_at = now + HEADPHONE_CHECK_S;
	if (now >= p->bluetooth_check_at) {
		find_bluetooth(p->bt_mac, sizeof(p->bt_mac));
		p->bluetooth_check_at = monotonic() + BLUETOOTH_CHECK_S;
	}
	const int best = best_output(p);
	if (best == p->output)
		return;
	if (best == TR_OUTPUT_SPEAKER || (p->output == TR_OUTPUT_BLUETOOTH && best == TR_OUTPUT_HEADPHONES)) {
		pause_playing(p);
	} else {
		close_pcm(p, 0);
		if (!open_pcm(p, (unsigned)p->info.samplerate))
			publish_state(p, TR_PLAYER_PAUSED);
	}
}

/* ---- the thread ---- */

static requests take_requests(tr_player *p, int *state, int *track, double *position)
{
	requests r;
	pthread_mutex_lock(&p->lock);
	const int idle = p->status.state != TR_PLAYER_PLAYING;
	const int waiting = p->want_track < 0 && p->want_seek < 0 && !p->want_toggle && !p->want_next && !p->want_prev &&
			    !p->want_rescan && !p->quit && p->pauses_asked == p->pauses_done;
	if (idle && waiting) {
		struct timespec until;
		clock_gettime(CLOCK_MONOTONIC, &until);
		until.tv_nsec += IDLE_WAIT_MS * 1000000L;
		if (until.tv_nsec >= 1000000000L) {
			until.tv_sec++;
			until.tv_nsec -= 1000000000L;
		}
		pthread_cond_timedwait(&p->wake, &p->lock, &until);
	}
	r = (requests){ p->want_track, p->want_seek, p->want_toggle, p->want_next, p->want_prev,
			p->want_rescan, p->quit, p->pauses_asked };
	p->want_track = p->want_seek = -1;
	p->want_toggle = p->want_next = p->want_prev = p->want_rescan = 0;
	*state = p->status.state;
	*track = p->status.track;
	*position = p->status.position;
	pthread_mutex_unlock(&p->lock);
	return r;
}

static void acknowledge_pause(tr_player *p, unsigned upto)
{
	pthread_mutex_lock(&p->lock);
	p->pauses_done = upto;
	pthread_cond_broadcast(&p->released);
	pthread_mutex_unlock(&p->lock);
}

static void apply_requests(tr_player *p, const requests *r, int state, int track, double position)
{
	if (r->rescan) {
		rescan(p, track);
		pthread_mutex_lock(&p->lock);
		track = p->status.track;
		pthread_mutex_unlock(&p->lock);
	}
	if (r->track >= 0 && r->track < p->n_paths)
		play_track(p, r->track);
	else if (r->toggle)
		toggle(p, state, track);
	else if (r->next && track + 1 < p->n_paths)
		play_track(p, track + 1);
	else if (r->prev && p->file && (position > RESTART_AFTER_S || track <= 0))
		seek_to(p, 0);
	else if (r->prev && track > 0)
		play_track(p, track - 1);
	if (r->seek >= 0)
		seek_to(p, r->seek);
	/* Last, so a release beats a play that arrived with it: an alarm must get the device. */
	if (r->pauses != p->pauses_done) {     /* only this thread writes pauses_done */
		pthread_mutex_lock(&p->lock);
		const int now_playing = p->status.state == TR_PLAYER_PLAYING;
		pthread_mutex_unlock(&p->lock);
		if (now_playing)
			pause_playing(p);
		acknowledge_pause(p, r->pauses);
	}
}

static void *player_thread(void *arg)
{
	tr_player *p = arg;
	rescan(p, -1);
	for (;;) {
		int state, track;
		double position;
		const requests r = take_requests(p, &state, &track, &position);
		if (r.quit)
			break;
		apply_requests(p, &r, state, track, position);
		pthread_mutex_lock(&p->lock);
		state = p->status.state;
		track = p->status.track;
		pthread_mutex_unlock(&p->lock);
		if (state == TR_PLAYER_PLAYING && p->pcm && p->file) {
			check_outputs(p);
			if (p->pcm && p->file)
				play_block(p, track);
		}
	}
	close_pcm(p, 0);
	close_track(p);
	return NULL;
}

/* ---- the public side ---- */

tr_player *tr_player_new(const char *dir, const char *fixed_device)
{
	tr_player *p = calloc(1, sizeof(*p));
	if (!p)
		return NULL;
	p->paths = calloc(TR_MUSIC_MAX_TRACKS, sizeof(track_path));
	if (!p->paths) {
		free(p);
		return NULL;
	}
	snprintf(p->dir, sizeof(p->dir), "%s", dir);
	if (fixed_device)
		snprintf(p->fixed_device, sizeof(p->fixed_device), "%s", fixed_device);
	mkdir(dir, 0755);
	p->want_track = p->want_seek = -1;
	p->status.track = -1;
	p->status.volume = DEFAULT_VOLUME;

	pthread_condattr_t monotonic_clock;
	pthread_condattr_init(&monotonic_clock);
	pthread_condattr_setclock(&monotonic_clock, CLOCK_MONOTONIC);
	pthread_mutex_init(&p->lock, NULL);
	pthread_cond_init(&p->wake, &monotonic_clock);
	pthread_cond_init(&p->released, &monotonic_clock);
	pthread_condattr_destroy(&monotonic_clock);

	pthread_attr_t attr;
	pthread_attr_init(&attr);
	pthread_attr_setstacksize(&attr, THREAD_STACK);
	const int err = pthread_create(&p->thread, &attr, player_thread, p);
	pthread_attr_destroy(&attr);
	if (err) {
		free(p->paths);
		free(p);
		return NULL;
	}
	return p;
}

void tr_player_free(tr_player *p)
{
	pthread_mutex_lock(&p->lock);
	p->quit = 1;
	pthread_cond_signal(&p->wake);
	pthread_mutex_unlock(&p->lock);
	pthread_join(p->thread, NULL);
	pthread_mutex_destroy(&p->lock);
	pthread_cond_destroy(&p->wake);
	pthread_cond_destroy(&p->released);
	free(p->paths);
	free(p);
}

static void wait_for_release(tr_player *p, unsigned asked)
{
	struct timespec until;
	clock_gettime(CLOCK_MONOTONIC, &until);
	until.tv_sec += RELEASE_TIMEOUT_S;
	while (p->pauses_done != asked)
		if (pthread_cond_timedwait(&p->released, &p->lock, &until) == ETIMEDOUT)
			break;
}

void tr_player_command(tr_player *p, tr_music_cmd cmd)
{
	pthread_mutex_lock(&p->lock);
	switch (cmd.kind) {
	case TR_CMD_PLAY_TRACK: p->want_track = cmd.arg; break;
	case TR_CMD_TOGGLE: p->want_toggle = 1; break;
	case TR_CMD_NEXT: p->want_next = 1; break;
	case TR_CMD_PREV: p->want_prev = 1; break;
	case TR_CMD_SEEK: p->want_seek = cmd.arg; break;
	case TR_CMD_RESCAN: p->want_rescan = 1; break;
	case TR_CMD_VOLUME:
		p->status.volume = tr_clamp(p->status.volume + cmd.arg, 0, TR_MUSIC_VOLUME_MAX);
		break;
	case TR_CMD_RELEASE: {
		const unsigned asked = ++p->pauses_asked;
		pthread_cond_signal(&p->wake);
		wait_for_release(p, asked);
		break;
	}
	default: break;
	}
	pthread_cond_signal(&p->wake);
	pthread_mutex_unlock(&p->lock);
}

void tr_player_status(tr_player *p, tr_music_status *out)
{
	pthread_mutex_lock(&p->lock);
	*out = p->status;
	pthread_mutex_unlock(&p->lock);
}

void tr_player_library(tr_player *p, tr_music_library *out)
{
	pthread_mutex_lock(&p->lock);
	if (out->version != p->library.version)
		*out = p->library;
	pthread_mutex_unlock(&p->lock);
}
