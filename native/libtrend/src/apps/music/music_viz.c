/* The visualiser: abstract 3D objects in the same shaded ASCII as the home screen icons, drawn by the
 * same renderer (mesh.c). A cube in the middle kicks with the bass, a ring of bars stands for the
 * spectrum with shards orbiting inside it, and behind them the character grid itself lights up in
 * rays and ripples.
 *
 * The PS1 feel comes from the geometry: blocky shapes whose positions snap to a coarse grid, so they
 * shiver slightly as they turn, the way that console's vertices did.
 *
 * The state is only what the music has done lately. Advancing moves it along. Drawing is a pure
 * function of it: the objects are rebuilt from scratch for each frame, because they change shape.
 */
#include <math.h>
#include <string.h>

#include "music_state.h"
#include "trend/mesh.h"

enum {
	N_BANDS = 12, N_BARS = N_BANDS * 2, N_SHARDS = 8,
	TICKS_PER_SECOND = 30, MAX_STEPS = 2,
	N_COLOURS = 7,
	GRID_COLS = 60, GRID_ROWS = 38,
	MAX_POINTS = 20000, MAX_FACES = (N_BARS + N_SHARDS + 1) * 6,
	MAX_FIELD_SHADE = 5,
};

#define TAU 6.2831853f
#define STEP_SECONDS (1.0f / TICKS_PER_SECOND)
#define BAND_FALL 0.84f                /* levels drop this much per step, and rise at once */
#define SPACING 0.06f                  /* between surface points: close enough to leave no holes */
#define SNAP 0.045f                    /* the grid positions snap to */
#define RING_RADIUS 2.1f
#define SHARD_RADIUS 1.35f

/* The icons' view of the world: config.py's CAM_Z, LIGHT and CW / CH. */
#define CAM_Z (-4.5f)
#define VIEW_K 54.0f
#define CELL_ASPECT (8.0f / 12.0f)

/* Palette indices in config.py's PALETTE, in rainbow order. */
static const int RAINBOW[N_COLOURS] = { 0, 6, 3, 1, 5, 2, 4 };
#define WHITE_INDEX 7

/* Which frequencies each band listens to, as whole cycles across the scope's samples. */
static const unsigned char BAND_CYCLES[N_BANDS] = { 1, 2, 3, 4, 5, 7, 9, 12, 16, 21, 27, 34 };

struct tr_music_viz {
	float bands[N_BANDS];
	float bass;
	float clock;
	float spin;                    /* turns faster when the music is louder */
	int64_t tick;                  /* the last tick stepped to, or -1 */
};

size_t tr_music_viz_size(void)
{
	return sizeof(tr_music_viz);
}

void tr_music_viz_init(tr_music_viz *out)
{
	memset(out, 0, sizeof(*out));
	out->tick = -1;
}

/* ---- listening ---- */

/* How much of one frequency is in the samples, 0..1 (Goertzel). */
static float band_level(const int16_t *samples, int cycles)
{
	const float coeff = 2.0f * cosf(TAU * (float)cycles / TR_MUSIC_SCOPE);
	float q1 = 0.0f, q2 = 0.0f;
	for (int i = 0; i < TR_MUSIC_SCOPE; i++) {
		const float q0 = coeff * q1 - q2 + (float)samples[i] / 32768.0f;
		q2 = q1;
		q1 = q0;
	}
	const float power = fmaxf(q1 * q1 + q2 * q2 - coeff * q1 * q2, 0.0f);
	return fminf(sqrtf(sqrtf(power) * 2.0f / TR_MUSIC_SCOPE) * 1.5f, 1.0f);
}

static void step(tr_music_viz *v, const tr_music_status *st)
{
	for (int b = 0; b < N_BANDS; b++)
		v->bands[b] = fmaxf(band_level(st->scope, BAND_CYCLES[b]), v->bands[b] * BAND_FALL);
	v->bass = fmaxf(v->bands[0], fmaxf(v->bands[1], v->bands[2]));
	v->clock += STEP_SECONDS;
	v->spin += STEP_SECONDS * (0.28f + 0.5f * v->bass);
}

void tr_music_viz_advance(tr_music_viz *v, const tr_music_status *status, double now)
{
	const int64_t tick = (int64_t)(now * TICKS_PER_SECOND);
	const int64_t behind = v->tick < 0 ? 1 : tick - v->tick;
	const int steps = behind < 0 ? 0 : behind > MAX_STEPS ? MAX_STEPS : (int)behind;
	v->tick = tick;
	if (status->state == TR_PLAYER_PAUSED)         /* frozen, to carry on from where it was */
		return;
	for (int i = 0; i < steps; i++)
		step(v, status);
}

/* ---- building the objects ---- */

typedef struct { float x, y, z; } vec3;

/* A mesh being filled in. */
typedef struct {
	float *pts, *fnrm, *fcen;
	int32_t *fstart, *fcol;
	int n_points, n_faces;
} builder;

static inline vec3 scale(vec3 a, float k) { return (vec3){ a.x * k, a.y * k, a.z * k }; }
static inline vec3 add(vec3 a, vec3 b) { return (vec3){ a.x + b.x, a.y + b.y, a.z + b.z }; }

static inline float snapped(float x)
{
	return roundf(x / SNAP) * SNAP;
}

static inline vec3 snapped3(vec3 a)
{
	return (vec3){ snapped(a.x), snapped(a.y), snapped(a.z) };
}

static inline void put3(float *dst, vec3 a)
{
	dst[0] = a.x;
	dst[1] = a.y;
	dst[2] = a.z;
}

/* One face: centre, outward normal, and the half-extents along two axes in the face. Stops quietly if
 * the mesh is full, which only ever loses the last few bits of a shape. */
static void add_face(builder *m, vec3 centre, vec3 normal, vec3 u, float hu, vec3 v, float hv, int colour)
{
	const int nu = tr_max((int)(2.0f * hu / SPACING), 2), nv = tr_max((int)(2.0f * hv / SPACING), 2);
	if (m->n_faces >= MAX_FACES || m->n_points + nu * nv > MAX_POINTS)
		return;
	const int f = m->n_faces++;
	m->fstart[f] = m->n_points;
	put3(m->fnrm + 3 * f, normal);
	put3(m->fcen + 3 * f, centre);
	m->fcol[f] = colour;
	for (int a = 0; a < nu; a++) {
		const float ka = ((float)a + 0.5f) / (float)nu * 2.0f - 1.0f;
		for (int b = 0; b < nv; b++) {
			const float kb = ((float)b + 0.5f) / (float)nv * 2.0f - 1.0f;
			const vec3 p = add(add(centre, scale(u, ka * hu)), scale(v, kb * hv));
			put3(m->pts + 3 * m->n_points++, p);
		}
	}
	m->fstart[m->n_faces] = m->n_points;
}

/* A box with its own axes, whose faces take a colour per axis, like the icons. */
static void add_box(builder *m, vec3 centre, const vec3 axes[3], const float half[3], const int colours[3])
{
	for (int axis = 0; axis < 3; axis++) {
		const int a = (axis + 1) % 3, b = (axis + 2) % 3;
		for (int sign = -1; sign <= 1; sign += 2) {
			const vec3 normal = scale(axes[axis], (float)sign);
			const vec3 c = add(centre, scale(normal, half[axis]));
			add_face(m, c, normal, axes[a], half[a], axes[b], half[b], colours[axis]);
		}
	}
}

/* Axes turned by the same three angles as render.py's matrix. */
static void turned_axes(float a, float b, float c, vec3 axes[3])
{
	const float ca = cosf(a), sa = sinf(a), cb = cosf(b), sb = sinf(b), cc = cosf(c), sc = sinf(c);
	axes[0] = (vec3){ cc * cb, sc * cb, -sb };
	axes[1] = (vec3){ cc * sb * sa - sc * ca, sc * sb * sa + cc * ca, cb * sa };
	axes[2] = (vec3){ cc * sb * ca + sc * sa, sc * sb * ca - cc * sa, cb * ca };
}

static inline int rainbow(int i)
{
	return RAINBOW[((i % N_COLOURS) + N_COLOURS) % N_COLOURS];
}

static void add_heart(builder *m, const tr_music_viz *v)
{
	vec3 axes[3];
	turned_axes(v->spin * 1.3f, v->spin * 1.9f, v->spin * 0.7f, axes);
	const float size = snapped(0.5f + 0.32f * v->bass);
	const float half[3] = { size, size, size };
	/* The colours walk round the wheel slowly. */
	const int shift = (int)(v->clock * 0.5f);
	const int colours[3] = { rainbow(shift), rainbow(shift + 2), rainbow(shift + 4) };
	add_box(m, (vec3){ 0.0f, 0.0f, 0.0f }, axes, half, colours);
}

/* Bars around a ring, mirrored so the spectrum runs up one side and down the other. Each stands up
 * and down from the ring's plane. */
static void add_bars(builder *m, const tr_music_viz *v)
{
	for (int i = 0; i < N_BARS; i++) {
		const int band = i < N_BANDS ? i : N_BARS - 1 - i;
		const float angle = TAU * (float)i / N_BARS;
		const float height = snapped(0.08f + 1.05f * v->bands[band]);
		const vec3 axes[3] = { { cosf(angle), 0.0f, sinf(angle) }, { 0.0f, 1.0f, 0.0f }, { -sinf(angle), 0.0f, cosf(angle) } };
		const float half[3] = { 0.07f, height, 0.09f };
		const int colour = rainbow(band * N_COLOURS / N_BANDS);
		const int colours[3] = { colour, WHITE_INDEX, colour };
		add_box(m, snapped3(scale(axes[0], RING_RADIUS)), axes, half, colours);
	}
}

/* Little blocks orbiting the cube, above and below the ring, thrown wider by the bass. */
static void add_shards(builder *m, const tr_music_viz *v)
{
	for (int i = 0; i < N_SHARDS; i++) {
		const float fi = (float)i;
		const float angle = TAU * fi / N_SHARDS - v->spin * 1.6f;
		const float radius = SHARD_RADIUS + 0.3f * v->bass;
		const float rise = (i % 2 ? 1.0f : -1.0f) * (0.95f + 0.3f * sinf(v->clock * 0.9f + fi * 2.1f));
		vec3 axes[3];
		turned_axes(v->spin * 3.0f + fi, v->spin * 2.0f, fi, axes);
		const float size = 0.11f + 0.05f * v->bands[i % N_BANDS];
		const float half[3] = { size, size, size };
		const int colour = rainbow(i + (int)(v->clock * 0.5f));
		const int colours[3] = { colour, colour, WHITE_INDEX };
		add_box(m, snapped3((vec3){ radius * cosf(angle), rise, radius * sinf(angle) }), axes, half, colours);
	}
}

/* ---- behind the objects ---- */

/* Cells the objects left empty light up in faint characters: a ray per band, reaching out as far as
 * that band is loud, with ripples running outward through them. */
static void fill_background(int32_t *grid, const tr_music_viz *v, int n_shades)
{
	const float cx = (GRID_COLS - 1) / 2.0f, cy = (GRID_ROWS - 1) / 2.0f;
	const float reach = 62.0f;
	for (int row = 0; row < GRID_ROWS; row++) {
		const float dy = ((float)row - cy) / CELL_ASPECT;
		for (int col = 0; col < GRID_COLS; col++) {
			int32_t *cell = grid + row * GRID_COLS + col;
			if (*cell)
				continue;
			const float dx = (float)col - cx;
			const float dist = sqrtf(dx * dx + dy * dy);
			const float turn = atan2f(dy, dx) / TAU + 0.5f;
			const int slice = tr_clamp((int)(turn * N_BARS), 0, N_BARS - 1);
			const int band = slice < N_BANDS ? slice : N_BARS - 1 - slice;
			const float level = v->bands[band];
			const float ray = level - dist / reach;
			const float ripple = sinf(dist * 0.55f - v->clock * 5.0f) * (0.08f + 0.22f * v->bass);
			const int shade = tr_min((int)((ray + ripple) * 7.0f), MAX_FIELD_SHADE);
			if (shade > 0)
				*cell = rainbow(band * N_COLOURS / N_BANDS) * n_shades + shade;
		}
	}
}

/* ---- to the screen ---- */

void tr_music_viz_draw(const tr_music_viz *v, const tr_music_theme *theme, tr_surface dst)
{
	float pts[MAX_POINTS * 3], fnrm[MAX_FACES * 3], fcen[MAX_FACES * 3];
	int32_t fstart[MAX_FACES + 1], fcol[MAX_FACES], grid[GRID_ROWS * GRID_COLS];
	builder m = { pts, fnrm, fcen, fstart, fcol, 0, 0 };
	fstart[0] = 0;
	add_heart(&m, v);
	add_bars(&m, v);
	add_shards(&m, v);

	/* The scene turns about the vertical, seen from a little above. */
	const float a = v->spin, tilt = 0.62f + 0.12f * sinf(v->clock * 0.23f);
	const float ca = cosf(a), sa = sinf(a), ct = cosf(tilt), st = sinf(tilt);
	const float r[9] = { ca, 0.0f, sa, st * sa, ct, -st * ca, -ct * sa, st, ct * ca };
	const tr_view view = { VIEW_K, CELL_ASPECT, CAM_Z, { -2.5f, 3.0f, -5.0f }, GRID_COLS, GRID_ROWS, theme->shades };
	const tr_mesh mesh = { pts, fstart, fnrm, fcen, fcol, m.n_faces };

	tr_fill_rect(dst, (tr_rect){ 0, dst.h, 0, dst.w }, 0xff000000u);
	tr_mesh_grid(mesh, r, view, grid);
	fill_background(grid, v, theme->shades);
	tr_grid_blit(grid, GRID_COLS, GRID_ROWS, theme->atlas, dst, (dst.w - GRID_COLS * theme->atlas.cw) / 2,
		     (dst.h - GRID_ROWS * theme->atlas.ch) / 2);
}
