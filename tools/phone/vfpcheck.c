/* Does a thread keep its NEON registers when a core is hot-plugged? Should say LOST 0 in every mode; before
 * kernel/vfp-hotplug.patch, "plug" lost them nearly every time. Takes CPU1 on and offline. The results are only
 * clean with no other thread using NEON on CPU1, so run it with nothing playing.
 *     gcc -O1 -mcpu=cortex-a7 -mfpu=neon-vfpv4 -pthread -o vfpcheck vfpcheck.c
 *     ./vfpcheck plug 50 40; ./vfpcheck plug 1000 8; ./vfpcheck sole 300 25; ./vfpcheck ctrl 200 20
 *
 * A thread pinned to one core loads known values into d8-d31 and blocks. Then, given <mode> <ms> <trials>:
 *   plug   thread on CPU1: take CPU1 offline for ms and bring it back, then wake the thread
 *   sole   thread on CPU0, CPU1 offline throughout: sleep for ms, so that CPU0 can enter its deepest idle
 *   ctrl   thread on CPU0, CPU1 left alone: sleep for ms */
#define _GNU_SOURCE
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static int go[2], done[2], home, woke_cpu, lost;
static uint64_t want[24], got[24];

static void pin(int cpu) { cpu_set_t s; CPU_ZERO(&s); CPU_SET(cpu, &s); sched_setaffinity(0, sizeof(s), &s); }
static int set_online(int v)
{
	int fd = open("/sys/devices/system/cpu/cpu1/online", O_WRONLY);
	const int ok = fd >= 0 && write(fd, v ? "1" : "0", 1) == 1;
	if (fd >= 0) close(fd);
	return ok;
}
static int is_online(void)
{
	char c = '?';
	int fd = open("/sys/devices/system/cpu/cpu1/online", O_RDONLY);
	if (fd >= 0) { if (read(fd, &c, 1) != 1) c = '?'; close(fd); }
	return c == '1';
}
static void sleep_ms(int ms) { struct timespec t = { ms / 1000, (ms % 1000) * 1000000L }; nanosleep(&t, NULL); }
static long c3(int cpu)
{
	char path[80]; long v = -1;
	snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/cpuidle/state2/usage", cpu);
	FILE *f = fopen(path, "r");
	if (f) { if (fscanf(f, "%ld", &v) != 1) v = -1; fclose(f); }
	return v;
}

static void *sentinel(void *arg)
{
	(void)arg;
	char b;
	for (;;) {
		pin(home);
		while (sched_getcpu() != home) usleep(500);
		__asm__ volatile("vldm %0, {d8-d23}\n\tvldm %1, {d24-d31}" : : "r"(want), "r"(want + 16) : "d8","d9","d10","d11","d12","d13","d14","d15","d16","d17","d18","d19","d20","d21","d22","d23","d24","d25","d26","d27","d28","d29","d30","d31","memory");
		if (write(done[1], "r", 1) != 1) return NULL;
		if (read(go[0], &b, 1) != 1) return NULL;
		__asm__ volatile("vstm %0, {d8-d23}\n\tvstm %1, {d24-d31}" : : "r"(got), "r"(got + 16) : "memory");
		woke_cpu = sched_getcpu();
		lost = memcmp(want, got, sizeof(want)) != 0;
		if (write(done[1], "d", 1) != 1) return NULL;
	}
}

int main(int argc, char **argv)
{
	if (argc != 4) {
		fprintf(stderr, "usage: vfpcheck plug|sole|ctrl <ms> <trials>\n");
		return 2;
	}
	const char *mode = argv[1];
	const int ms = atoi(argv[2]), trials = atoi(argv[3]);
	const int plug = !strcmp(mode, "plug"), sole = !strcmp(mode, "sole");
	pthread_t th;
	char b;
	int n = 0, nlost = 0, cycled = 0, onhome = 0;
	for (int i = 0; i < 24; i++) want[i] = 0x0101010101010101ULL * (uint64_t)(i + 8);
	if (pipe(go) || pipe(done)) return 1;
	home = plug ? 1 : 0;
	pin(0);
	for (int k = 0; k < 100 && !is_online(); k++) { set_online(1); sleep_ms(20); }
	pthread_create(&th, NULL, sentinel, NULL);
	const long c30 = c3(0);
	for (int i = 0; i < trials; i++) {
		if (plug) for (int k = 0; k < 100 && !is_online(); k++) { set_online(1); if (!is_online()) sleep_ms(20); }
		if (sole) for (int k = 0; k < 100 && is_online(); k++) { set_online(0); if (is_online()) sleep_ms(20); }
		if (read(done[0], &b, 1) != 1) return 1;
		if (plug) {
			cycled += set_online(0) && !is_online();
			sleep_ms(ms);
			for (int k = 0; k < 100 && !is_online(); k++) { set_online(1); if (!is_online()) sleep_ms(20); }
		} else
			sleep_ms(ms);
		if (write(go[1], "g", 1) != 1) return 1;
		if (read(done[0], &b, 1) != 1) return 1;
		n++;
		onhome += woke_cpu == home;
		if (lost && nlost++ < 2) {
			printf("  LOST trial %d on cpu%d:", i, woke_cpu);
			for (int r = 0; r < 8; r++) printf(" d%d=%016llx", r + 8, (unsigned long long)got[r]);
			printf("\n");
		}
	}
	printf("%s %dms: %d trials, cycled %d, woke on home cpu %d, cpu0 C3 +%ld, LOST %d\n", mode, ms, n, cycled, onhome, c3(0) - c30, nlost);
	for (int k = 0; k < 100 && !is_online(); k++) { set_online(1); sleep_ms(20); }
	return 0;
}
