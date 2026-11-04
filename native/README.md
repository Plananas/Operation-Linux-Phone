# native/: all the C in TREND OS

| Path | What it is | How it runs |
|---|---|---|
| `libtrend/` | The C core: pixels, 2D drawing, 3D meshes, visualisers | Shared library, called from Python |
| `boot/` | `bootanim`, `charger`, `fbpan`: small static programs in the ramdisk | Standalone, before Python exists |

Our kernel is the other C in the project. It's built from Samsung's source (`tools/kernel/`).

## Where the line sits

**C does the work that repeats:** anything that touches many pixels or samples on every frame.

**Python decides what happens:** app logic, layout, screens, starting and stopping things, and
talking to `bluetoothctl`, `wpa_cli` and similar tools.

Move code to C when all of these are true:

1. It runs often: every frame, or on many screens.
2. A measurement on the phone shows it costs real time.
3. It will still pay off as more apps are added.

`tos/native.py` is the only Python file that may import `ctypes`. Everything else calls ordinary
Python functions and passes numpy arrays.

## Style

libtrend is written in a functional style that doesn't give up speed:

- **Functions don't remember anything.** No globals or `static` state. What they need arrives as
  arguments, and what they produce leaves through a return value or an output handed to them.
- **Inputs are `const`.** The one thing a function may write to is the output it was given, such as
  a `tr_surface`. Hot loops write into these caller-owned buffers rather than allocating.
- **Small structs travel by value** (`tr_surface`, `tr_rect`, `tr_view`).
- **Each hot loop is a small helper**, such as `rotate`, `shade_of` or `blit_tile`, which the
  compiler inlines.

Because no state is hidden, every function can be tested alone and called from any thread.

## Adding to libtrend

1. Declare the function in `include/trend/<module>.h` and write it in `src/<module>.c`.
2. Add a test to `tests/test_libtrend.c`.
3. Add its signature to `_SIGNATURES` in `tos/native.py`, with a Python wrapper below it.
4. Measure on the phone before and after. In-order Cortex-A7 notes are in `PLAN.md`.

## Building and testing

```sh
cd native/libtrend
make test     # unit tests under the address and undefined-behaviour sanitizers
make          # libtrend.so for this machine
```

`tools/deploy.sh` builds the library on the phone with the NEON flags. The NEON paths only run
there, so also run the tests on the phone after changing them.
