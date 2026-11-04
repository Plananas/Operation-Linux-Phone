/* fbpan: point the sprdfb display controller at /dev/fb0 page N (default 0).
 * After an early-suspend/late-resume cycle the controller still scans out the
 * bootloader's logo copy until FBIOPAN_DISPLAY sets the framebuffer address.
 * Usage: fbpan [page] */
#include <fcntl.h>
#include <linux/fb.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

int main(int argc, char **argv) {
	struct fb_var_screeninfo v;
	int page = argc > 1 ? atoi(argv[1]) : 0;
	int fd = open("/dev/fb0", O_RDWR);
	if (fd < 0 || ioctl(fd, FBIOGET_VSCREENINFO, &v)) { perror("fb0"); return 1; }
	/* pan away and back so the driver always reprograms the scanout address */
	v.yoffset = (page ? 0 : v.yres);
	ioctl(fd, FBIOPAN_DISPLAY, &v);
	v.yoffset = page * v.yres;
	if (ioctl(fd, FBIOPAN_DISPLAY, &v)) { perror("pan"); return 1; }
	close(fd);
	return 0;
}
