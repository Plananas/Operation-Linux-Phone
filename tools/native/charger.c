/* charger: TREND OS charging screen, run by the ramdisk init when the bootloader started the
 * phone because a charger was plugged in (kernel cmdline androidboot.mode=charger).
 *
 * Look (assets pre-rendered by mkcharger.py -> /charger.bin): "TREND OS" title, a battery whose
 * inside is animated ASCII "liquid" (wavy surface, denser characters deeper down, rising bubbles
 * while charging; green / yellow < 40 % / red < 15 %), big percentage, live status line, hint.
 * Falls back to plain rectangles + seven-segment digits if the asset file is missing.
 *
 * - screen off after 15 s; short Power press shows it again
 * - hold Power >= 1.5 s  -> exit 0  (init continues into the normal TREND OS boot)
 * - charger unplugged    -> exit 2  (init powers off)
 * Display wake: earlysuspend dance (mem -> on -> wait_for_fb_wake -> pan), as elsewhere.
 * Usage: charger [/charger.bin]
 */
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <math.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static int fbfd, W, H;
static uint8_t *fb;                 /* pages 0 and 1 (double buffered) */
static int page;                    /* page currently on screen */
static uint8_t *buf;                /* off-screen frame */
static struct fb_var_screeninfo var;

/* ---- assets ---- */
static int have_assets, ntiles, ns, tch, tcw, bigw, bigh, nbig, sfirst, scount, smw, smh, ttw, tth;
static uint8_t *tiles, *bigm, *smallm, *title;
static char bigchars[32];

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }
static void sysw(const char *p, const char *v) { int f = open(p, O_WRONLY); if (f >= 0) { if (write(f, v, strlen(v)) < 0) {} close(f); } }
static int sysr(const char *p, char *buf, int n) {
	int f = open(p, O_RDONLY); if (f < 0) return -1;
	int k = read(f, buf, n - 1); close(f); if (k < 0) k = 0; buf[k] = 0;
	while (k && (buf[k - 1] == '\n' || buf[k - 1] == ' ')) buf[--k] = 0;
	return k;
}

static int load_assets(const char *path) {
	FILE *f = fopen(path, "rb"); if (!f) return 0;
	char mg[4]; uint32_t v[4];
	if (fread(mg, 1, 4, f) != 4 || memcmp(mg, "CHGR", 4) || fread(v, 4, 1, f) != 1) goto bad;
	if (fread(v, 4, 4, f) != 4) goto bad;
	ntiles = v[0]; ns = v[1]; tch = v[2]; tcw = v[3];
	tiles = malloc((size_t)ntiles * tch * tcw * 4);
	if (fread(tiles, 1, (size_t)ntiles * tch * tcw * 4, f) != (size_t)ntiles * tch * tcw * 4) goto bad;
	if (fread(v, 4, 3, f) != 3 || v[0] >= sizeof bigchars) goto bad;
	nbig = v[0]; bigw = v[1]; bigh = v[2];
	if (fread(bigchars, 1, nbig, f) != (size_t)nbig) goto bad;
	bigm = malloc((size_t)nbig * bigw * bigh);
	if (fread(bigm, 1, (size_t)nbig * bigw * bigh, f) != (size_t)nbig * bigw * bigh) goto bad;
	if (fread(v, 4, 4, f) != 4) goto bad;
	sfirst = v[0]; scount = v[1]; smw = v[2]; smh = v[3];
	smallm = malloc((size_t)scount * smw * smh);
	if (fread(smallm, 1, (size_t)scount * smw * smh, f) != (size_t)scount * smw * smh) goto bad;
	if (fread(v, 4, 2, f) != 2) goto bad;
	ttw = v[0]; tth = v[1];
	title = malloc((size_t)ttw * tth * 4);
	if (fread(title, 1, (size_t)ttw * tth * 4, f) != (size_t)ttw * tth * 4) goto bad;
	fclose(f); return 1;
bad:
	fclose(f); return 0;
}

/* ---- display ---- */
static void pan_to(int p) {
	var.yoffset = p * H; ioctl(fbfd, FBIOPAN_DISPLAY, &var);
	uint32_t z = 0; ioctl(fbfd, FBIO_WAITFORVSYNC, &z);   /* old page is off screen after this */
	page = p;
}
static void pan0(void) { pan_to(page); }
/* Copy buf into the hidden page and flip. The title and hint never change, so after both pages
 * have had one full copy only the rows with the battery and the text are copied (~60 %). */
#define DYN_Y0 110
#define DYN_Y1 620
static void present(void) {
	static int full_copies = 2;
	int p = page ^ 1;
	size_t row = (size_t)W * 4;
	if (full_copies > 0) { memcpy(fb + (size_t)p * H * row, buf, H * row); full_copies--; }
	else memcpy(fb + (size_t)p * H * row + DYN_Y0 * row, buf + DYN_Y0 * row, (DYN_Y1 - DYN_Y0) * row);
	pan_to(p);
}
static void screen_off(void) { sysw("/sys/power/state", "mem"); }
static void screen_on(void) {
	sysw("/sys/power/state", "on");
	int f = open("/sys/power/wait_for_fb_wake", O_RDONLY);
	if (f >= 0) { char c; if (read(f, &c, 1) < 0) {} close(f); }
	pan0();
	sysw("/sys/class/backlight/panel/brightness", "160");
}

/* ---- drawing primitives (into the off-screen buffer `buf`, then one copy to the fb) ---- */
static void rect(int x0, int y0, int x1, int y1, uint8_t r, uint8_t g, uint8_t b) {
	if (x0 < 0) x0 = 0;
	if (y0 < 0) y0 = 0;
	if (x1 > W) x1 = W;
	if (y1 > H) y1 = H;
	for (int y = y0; y < y1; y++) {
		uint8_t *p = buf + ((size_t)y * W + x0) * 4;
		for (int x = x0; x < x1; x++, p += 4) { p[0] = r; p[1] = g; p[2] = b; p[3] = 0; }
	}
}
static void tile(int t, int x, int y) {
	if (t <= 0 || t >= ntiles || x < 0 || y < 0 || x + tcw > W || y + tch > H) return;
	for (int r = 0; r < tch; r++)
		memcpy(buf + ((size_t)(y + r) * W + x) * 4, tiles + ((size_t)t * tch + r) * tcw * 4, tcw * 4);
}
static void mask(const uint8_t *m, int w, int h, int x, int y, int r, int g, int b) {
	for (int yy = 0; yy < h; yy++) {
		if (y + yy < 0 || y + yy >= H) continue;
		for (int xx = 0; xx < w; xx++) {
			int a = m[yy * w + xx], X = x + xx;
			if (!a || X < 0 || X >= W) continue;
			uint8_t *p = buf + ((size_t)(y + yy) * W + X) * 4;
			p[0] = p[0] + ((r - p[0]) * a >> 8); p[1] = p[1] + ((g - p[1]) * a >> 8); p[2] = p[2] + ((b - p[2]) * a >> 8);
		}
	}
}
static void text_small(const char *s, int cx, int y, int r, int g, int b) {
	int n = strlen(s), x = cx - n * smw / 2;
	for (int i = 0; i < n; i++, x += smw) {
		int c = (unsigned char)s[i] - sfirst;
		if (c >= 0 && c < scount) mask(smallm + (size_t)c * smw * smh, smw, smh, x, y, r, g, b);
	}
}
static void text_big(const char *s, int cx, int y, int r, int g, int b) {
	int n = strlen(s), x = cx - n * bigw / 2;
	for (int i = 0; i < n; i++, x += bigw) {
		const char *p = strchr(bigchars, s[i]);
		if (p) mask(bigm + (size_t)(p - bigchars) * bigw * bigh, bigw, bigh, x, y, r, g, b);
	}
}

/* ---- fallback look (no assets): seven-segment digits ---- */
static void digit(int d, int x, int y, int w, int h, int t, uint8_t r, uint8_t g, uint8_t b) {
	static const uint8_t seg[10] = {0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f};
	int m = (h - t) / 2, s = seg[d];
	if (s & 0x01) rect(x + t, y, x + w - t, y + t, r, g, b);
	if (s & 0x02) rect(x + w - t, y + t, x + w, y + m + t / 2, r, g, b);
	if (s & 0x04) rect(x + w - t, y + m + t, x + w, y + h - t, r, g, b);
	if (s & 0x08) rect(x + t, y + h - t, x + w - t, y + h, r, g, b);
	if (s & 0x10) rect(x, y + m + t, x + t, y + h - t, r, g, b);
	if (s & 0x20) rect(x, y + t, x + t, y + m + t / 2, r, g, b);
	if (s & 0x40) rect(x + t, y + m, x + w - t, y + m + t, r, g, b);
}
static void draw_plain(int cap) {
	rect(0, 0, W, H, 0, 0, 0);
	int bx0 = W / 2 - 80, bx1 = W / 2 + 80, by0 = 210, by1 = 510;
	rect(bx0, by0, bx1, by1, 200, 200, 200); rect(bx0 + 6, by0 + 6, bx1 - 6, by1 - 6, 0, 0, 0);
	int ih = by1 - by0 - 28;
	rect(bx0 + 14, by1 - 14 - ih * cap / 100, bx1 - 14, by1 - 14, 70, 220, 110);
	char s[8]; snprintf(s, sizeof s, "%d", cap);
	int x = W / 2 - (int)strlen(s) * 34;
	for (int i = 0; s[i]; i++, x += 68) digit(s[i] - '0', x, 570, 54, 96, 12, 230, 230, 230);
}

/* ---- the TREND OS look ---- */
static uint32_t hash3(int a, int b, int c) {
	uint32_t h = a * 374761393u + b * 668265263u + c * 2147483647u;
	h = (h ^ (h >> 13)) * 1274126177u; return h ^ (h >> 16);
}
static void draw(int cap, int charging, int full, double volt, double temp, double t) {
	if (!have_assets) { draw_plain(cap); return; }
	rect(0, 0, W, H, 0, 0, 0);
	for (int r = 0; r < tth && 22 + r < H; r++) memcpy(buf + (size_t)(22 + r) * W * 4, title + (size_t)r * ttw * 4, ttw * 4);

	int col = cap < 15 ? 0 : cap < 40 ? 3 : 1;                         /* palette: red/yellow/green */
	int pr = cap < 15 ? 255 : cap < 40 ? 255 : 70, pg = cap < 15 ? 70 : cap < 40 ? 215 : 255, pb = cap < 15 ? 70 : cap < 40 ? 50 : 110;
	/* battery body: crisp outline, ASCII liquid inside */
	int cols = 20, rows = 24;
	int ix0 = (W - cols * tcw) / 2, iy0 = 150, ix1 = ix0 + cols * tcw, iy1 = iy0 + rows * tch;
	int o = 10, th = 4;                                               /* gap + outline thickness */
	uint8_t gr = 150;
	rect(ix0 - o - th, iy0 - o - th, ix1 + o + th, iy0 - o, gr, gr, gr);
	rect(ix0 - o - th, iy1 + o, ix1 + o + th, iy1 + o + th, gr, gr, gr);
	rect(ix0 - o - th, iy0 - o, ix0 - o, iy1 + o, gr, gr, gr);
	rect(ix1 + o, iy0 - o, ix1 + o + th, iy1 + o, gr, gr, gr);
	rect(W / 2 - 34, iy0 - o - th - 16, W / 2 + 34, iy0 - o - th, gr, gr, gr);   /* terminal */

	double level = rows * cap / 100.0;
	for (int c = 0; c < cols; c++) {
		double surf = level;
		if (cap < 100) surf += 0.55 * sin(c * 0.55 + t * 2.6) + 0.30 * sin(c * 1.30 - t * 1.7);
		for (int k = 0; k < rows; k++) {                               /* k: rows from the bottom */
			double d = surf - (k + 0.5);
			if (d < 0) continue;
			double depth = d / (level > 1 ? level : 1);                /* 0 at the surface .. 1 at the bottom */
			int idx = d < 0.9 ? 4 : 5 + (int)(depth * (ns - 5));       /* '~' at the surface, denser deeper */
			if (idx > ns - 1) idx = ns - 1;
			if ((hash3(c, k, (int)(t * 5)) & 7) == 0 && idx > 5) idx--; /* gentle shimmer */
			tile(col * ns + idx, ix0 + c * tcw, iy1 - (k + 1) * tch);
		}
	}
	if (charging && !full) {                                           /* rising bubbles */
		for (int b = 0; b < 5; b++) {
			int c = (b * 7 + 3) % cols;
			double span = level - 1.0; if (span < 2) break;
			double k = fmod(t * (1.2 + 0.25 * b) + b * 1.9, span);
			tile(7 * ns + 3 + (b & 1), ix0 + c * tcw, iy1 - ((int)k + 1) * tch);   /* white '-'/'~' */
		}
	}

	char s[32];
	snprintf(s, sizeof s, "%d%%", cap);
	text_big(s, W / 2, iy1 + 34, 235, 235, 235);
	const char *state = full ? "fully charged" : charging ? "charging" : "not charging";
	snprintf(s, sizeof s, "%s  %.2f V  %.1f C", state, volt, temp);
	text_small(s, W / 2, iy1 + 34 + bigh + 6, pr, pg, pb);
	text_small("hold power to start", W / 2, H - 50, 110, 110, 110);
}

int main(int argc, char **argv) {
	fbfd = open("/dev/fb0", O_RDWR);
	if (fbfd < 0 || ioctl(fbfd, FBIOGET_VSCREENINFO, &var)) return 1;
	W = var.xres; H = var.yres;
	fb = mmap(NULL, (size_t)W * H * 4 * 2, PROT_READ | PROT_WRITE, MAP_SHARED, fbfd, 0);
	buf = malloc((size_t)W * H * 4);
	if (fb == MAP_FAILED || !buf) return 1;
	have_assets = load_assets(argc > 1 ? argv[1] : "/charger.bin");
	int kfd = open("/dev/input/event0", O_RDONLY | O_NONBLOCK);
	sysw("/sys/power/wake_lock", "trendos-charger");

	char b[64]; int cap = 0, charging = 1, full = 0, unplugged = 0, on = 1;
	double volt = 0, temp = 0, t_on = now(), t_stat = -1, down_t = -1, t_draw = -1;
	long last_sig = -1;
	memset(buf, 0, (size_t)W * H * 4); memset(fb, 0, (size_t)W * H * 4 * 2); page = 0;
	screen_off(); usleep(300000); screen_on();                      /* leave the bootloader logo */
	for (;;) {
		double t = now();
		if (t - t_stat >= 1.0) {
			t_stat = t;
			if (sysr("/sys/class/power_supply/battery/capacity", b, sizeof b) > 0) cap = atoi(b);
			if (sysr("/sys/class/power_supply/battery/voltage_now", b, sizeof b) > 0) volt = atoi(b) / 1e6;
			if (sysr("/sys/class/power_supply/battery/temp", b, sizeof b) > 0) temp = atoi(b) / 10.0;
			if (sysr("/sys/class/power_supply/battery/status", b, sizeof b) > 0) {
				charging = !strcmp(b, "Charging"); full = !strcmp(b, "Full") || cap >= 100;
				unplugged = !strcmp(b, "Discharging") ? unplugged + 1 : 0;
			}
			if (unplugged >= 3) return 2;
		}
		/* redraw: 15 fps while the liquid animates; otherwise only when something shown changed */
		int animating = charging && !full;
		long sig = cap * 1000000L + charging * 100000L + full * 10000L + (long)(volt * 100) * 10 + (long)(temp) % 10;
		if (on && (animating ? t - t_draw >= 1.0 / 15 : sig != last_sig)) {
			draw(cap, charging, full, volt, temp, t); present();
			t_draw = t; last_sig = sig;
		}
		if (on && t - t_on > 15) { screen_off(); on = 0; }
		if (down_t >= 0 && t - down_t >= 1.5) {
			if (!on) screen_on();
			memset(fb, 0, (size_t)W * H * 4 * 2); pan_to(page);   /* blank both pages, boot */
			return 0;
		}
		struct pollfd p = {kfd, POLLIN, 0};
		poll(&p, 1, on && charging && !full ? 20 : 250);
		struct input_event ev;
		while (kfd >= 0 && read(kfd, &ev, sizeof ev) == sizeof ev) {
			if (ev.type != EV_KEY || ev.code != KEY_POWER) continue;
			if (ev.value == 1) down_t = now();
			else if (ev.value == 0) {
				if (down_t >= 0 && now() - down_t < 1.5) { if (!on) { screen_on(); on = 1; last_sig = -1; } t_on = now(); }
				down_t = -1;
			}
		}
	}
}
