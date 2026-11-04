# native/: all the C in TREND OS

| Path | What it is | How it runs |
|---|---|---|
| `libtrend/` | The C core: pixels, 2D drawing, 3D meshes, visualisers, apps | Shared library, called from Python |
| `player/` | The music player: finds, decodes and plays files on its own thread | Shared library, loaded when Music first opens |
| `filesd/` | The web server behind the Files app | Its own program, started by the app, running without root |
| `webd/` | The Web app's browser engine and chat agent | Its own program, started twice by the app, running without root |
| `boot/` | `bootanim`, `charger`, `fbpan`: small static programs in the ramdisk | Standalone, before Python exists |

Our kernel is the other C in the project. It's built from Samsung's source (`kernel/`).

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

Move the whole loop, not just its body. Each Python-to-C call costs about 0.1 ms on the phone, so
230 calls to draw a card's scanlines cost more than the drawing did. One `tr_fill_stripes` call
fixed that.

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

`player/` is the one exception, because playing audio is state. It's a separate library so that
libtrend stays pure and the shell still starts without it, and its state lives behind an explicit
handle rather than in globals.

`filesd/` is separate for a different reason: it reads whatever the network sends, so it runs in its own
process as its own user. `http.c` holds everything that only looks at bytes, and `filesd.c` does the I/O.

`webd/` is separate for the same reason, and it reaches the whole internet. Its parts that only look at bytes
(`doc.c`, `url.c`, `html.c`, `json.c`, `ascii.c`) are pure and tested alone. The rest does the I/O.

## Adding to libtrend

1. Declare the function in `include/trend/<module>.h` and write it in `src/<module>.c`.
2. Add a test to `tests/test_libtrend.c`.
3. Add its signature to `_SIGNATURES` in `tos/native.py`, with a Python wrapper below it.
4. Measure on the phone before and after. In-order Cortex-A7 notes are in `PLAN.md`.

## Apps in C

An app can live entirely in `src/apps/<app>/`, with a thin class in `tos/apps/<app>/app.py`
connecting it to the shell. Each app has its own folder on both sides. Calculator is the example:

- `expr.c`: the pure logic, usable by anything.
- `apps/calculator/calculator.c`: behaviour. The state is opaque to Python. Each function takes the state in
  and writes the next state out.
- `apps/calculator/calculator_view.c`: drawing, a pure function from state and time to pixels. Redraw the whole
  app area each time rather than caching tiles, unless a measurement says otherwise.
- `tos/apps/calculator/app.py`: forwards touches, and supplies the fonts PIL rasterises once.

Apps that drive hardware or run tools like `bluetoothctl` usually keep that part in Python, in a
worker thread, and pass the results to C. Music is the all-C alternative: `src/apps/music/` turns
touches into commands, and `player/` carries them out and reports back a status to draw. Python only
passes them across.

## Building and testing

```sh
cd native/libtrend
make test     # unit tests under the address and undefined-behaviour sanitizers
make          # libtrend.so for this machine
```

`filesd/` has `make test` too: unit tests, then a real server attacked over sockets, under the sanitizers.
Also run `tests/test_server.py /usr/local/lib/trendos/filesd` on the phone after changing it, because the
phone is where it starts as root, so some bugs only show there.

`webd/` has `make test` for its pure parts. The whole program needs OpenSSL and stb headers, which the phone has, so
it's built there by `deploy.sh`.

`player/` needs ALSA and libsndfile headers, so build and test it on the phone. The phone has no
`make`, so run the compile lines from `player/Makefile` by hand.

`tools/deploy.sh` builds the library on the phone with the NEON flags. The NEON paths only run
there, so also run the tests on the phone after changing them.
