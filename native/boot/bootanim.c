/* bootanim: TREND OS "loading" spin, started by the ramdisk init right after the early logo.
 * Plays pre-rendered ASCII-cube frames (made by `cube.py --boot-anim`) into the cube area of
 * /dev/fb0, double-buffered with FBIOPAN_DISPLAY. Frame k = floor(t * fps) % n where t is
 * CLOCK_MONOTONIC, so cube.py can take over from exactly the same pose. Keeps running across
 * switch_root (everything is loaded into memory first). Stops on SIGTERM (sent by cube.py).
 *
 * File format (little endian): "BANM", n, rows, cols, ch, cw, top, fps, ntiles (u32 each),
 *   tiles[ntiles][ch][cw][4] (RGBX), grids[n][rows][cols] (u8 tile index)
 * Usage: bootanim frames.bin [pidfile]   (forks to background once loaded)
 */
#include <fcntl.h>
#include <linux/fb.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stop;
static void on_term(int s) { (void)s; stop = 1; }

static double now(void) {
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

int main(int argc, char **argv) {
	uint32_t h[8];
	char magic[4];
	if (argc < 2) return 2;
	FILE *f = fopen(argv[1], "rb");
	if (!f || fread(magic, 1, 4, f) != 4 || memcmp(magic, "BANM", 4) || fread(h, 4, 8, f) != 8) return 1;
	uint32_t n = h[0], rows = h[1], cols = h[2], ch = h[3], cw = h[4], top = h[5], fps = h[6], nt = h[7];
	size_t tsz = (size_t)nt * ch * cw * 4, gsz = (size_t)n * rows * cols;
	uint8_t *tiles = malloc(tsz), *grids = malloc(gsz);
	if (!tiles || !grids || fread(tiles, 1, tsz, f) != tsz || fread(grids, 1, gsz, f) != gsz) return 1;
	fclose(f);

	int fd = open("/dev/fb0", O_RDWR);
	struct fb_var_screeninfo v;
	if (fd < 0 || ioctl(fd, FBIOGET_VSCREENINFO, &v)) return 1;
	uint32_t W = v.xres, H = v.yres, stride = W * 4;
	if (cols * cw > W || top + rows * ch > H) return 1;
	uint8_t *fb = mmap(NULL, (size_t)stride * H * 2, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (fb == MAP_FAILED) return 1;

	/* loaded: detach so init can continue (and later delete the ramdisk) */
	pid_t pid = fork();
	if (pid < 0) return 1;
	if (pid > 0) {
		if (argc > 2) { FILE *p = fopen(argv[2], "w"); if (p) { fprintf(p, "%d\n", pid); fclose(p); } }
		return 0;
	}
	setsid();
	signal(SIGTERM, on_term);
	signal(SIGHUP, SIG_IGN);

	int page = 1;
	while (!stop) {
		double t = now();
		uint32_t k = (uint32_t)((uint64_t)(t * fps) % n);
		const uint8_t *g = grids + (size_t)k * rows * cols;
		uint8_t *dst = fb + (size_t)page * stride * H + (size_t)top * stride;
		for (uint32_t r = 0; r < rows; r++)
			for (uint32_t y = 0; y < ch; y++) {
				uint8_t *row = dst + (size_t)(r * ch + y) * stride;
				for (uint32_t c = 0; c < cols; c++)
					memcpy(row + (size_t)c * cw * 4,
					       tiles + ((size_t)g[r * cols + c] * ch + y) * cw * 4, cw * 4);
			}
		if (stop) break;   /* never flip after being told to stop */
		v.yoffset = page * H;
		ioctl(fd, FBIOPAN_DISPLAY, &v);
		page ^= 1;
		double next = ((uint64_t)(t * fps) + 1) / (double)fps, d = next - now();
		if (d > 0) usleep((useconds_t)(d * 1e6));
	}
	return 0;
}
