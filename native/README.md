# native/: all the C in TREND OS

| Path | What | How it runs |
|---|---|---|
| `libtrend/` | Pixels, 2D, 3D meshes, visualisers, apps | Shared library, called from Python |
| `player/` | Finds, decodes and plays music on its own thread | Shared library, loaded when Music first opens |
| `filesd/` | Files app's web server | Own program, no root after startup |
| `webd/` | Web app's browser engine and chat agent | Own program, started twice, no root |
| `boot/` | `bootanim`, `charger`, `fbpan` | Static, in the ramdisk |

## C or Python

C does what repeats (many pixels or samples per frame). Python decides what happens: app logic, layout, starting things, talking to tools like `bluetoothctl`.

Move code to C only if it runs often, a measurement on the phone shows real cost, and it will keep paying off. Move the whole loop, because each Python-to-C call costs ~0.1 ms. `tos/native.py` is the only Python file that may import `ctypes`.

## Style

Functional, without giving up speed:
- No globals or `static` state: inputs arrive as `const` arguments, and output goes to a return value or a caller-owned buffer.
- Small structs go by value (`tr_surface`, `tr_rect`, `tr_view`).
- Each hot loop is a small inlined helper.

Exceptions: `player/` holds audio state behind an explicit handle, in its own library so the shell starts without it. `filesd/` and `webd/` read the network, so they run as their own processes and users, and their byte-only parts (`http.c`; `doc.c url.c html.c json.c ascii.c gemini.c`) are pure and tested alone.

## Adding to libtrend

1. Declare in `include/trend/<module>.h`, write in `src/<module>.c`.
2. Test in `tests/test_libtrend.c`.
3. Add the signature to `_SIGNATURES` in `tos/native.py`, with a wrapper.
4. Measure on the phone before and after.

## Apps in C

Each app has `src/apps/<app>/` and a thin `tos/apps/<app>/app.py`. Calculator is the example: `<app>.c` turns state into next state, and `<app>_view.c` is a pure function from state and time to pixels, redrawing the whole area unless a measurement says otherwise. Python forwards touches and supplies fonts. Hardware or tool-driving parts usually stay in a Python worker thread; Music is the all-C alternative, using `player/`.

## Building and testing

- `libtrend/`, `filesd/`, `webd/`: `make test` on the laptop, under sanitizers. `webd` tests only its pure parts.
- `filesd/`: also run `tests/test_server.py /usr/local/lib/trendos/filesd` on the phone, where it starts as root.
- `webd/`, `player/`: need headers the laptop lacks (OpenSSL and stb; ALSA and libsndfile), so build on the phone. It has no `make`, so run the compile lines by hand. `deploy.sh` builds everything.
- NEON paths only run on the phone, so run the tests there after changing them.
