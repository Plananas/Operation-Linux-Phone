"""Spotify app: the phone itself is the player (go-librespot, the `spotify` service, plays through
the speaker); this app is its screen. Talks to the player's local API on 127.0.0.1:3678.

Screens:
  pair     first run: shows the code to enter at spotify.com/pair on any other device; the
           player saves the login, so this is only needed once
  library  Liked Songs + your playlists (drag to scroll, tap to open)
  tracks   a playlist's songs: tap one to play from it, or Play / Shuffle at the top
The now-playing panel (track, progress, prev / play-pause / next, volume) is docked at the bottom
of the library and track screens.

All network calls run in short background threads; the UI only reads the latest results.
List screens are rendered once into a tall image and scrolled by cropping it.
"""
import json, subprocess, threading, time
import urllib.error, urllib.request

import numpy as np
from PIL import Image, ImageDraw

from ..config import W, TOP, APP_H, ACCENT, GREY, DIM, TEXT, PALETTE, SPOTIFY
from ..gfx import canvas, centre_text, font, to_rgbx
from .base import App

API = "http://127.0.0.1:3678"
POLL_EVERY = 1.0                       # s between status polls while the app is on screen
LIBRARY_MAX_AGE = 120.0                # s before the playlist list is fetched again
TRACKS_POLL = 0.7                      # s between polls while a track list is still loading
GREEN = PALETTE[SPOTIFY]
PANEL_H = 196                          # now-playing panel at the bottom of the app area
LIST_H = APP_H - PANEL_H
ROW_H, HEAD_H = 64, 56
DRAG_START = 12


# ---- player API ------------------------------------------------------------------------
def api(method, path, body=None, timeout=4.0):
    """(HTTP status, parsed JSON or None); status 0 if the player is unreachable."""
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def _bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def fit(d, text, f, maxw):
    """text shortened with an ellipsis to fit maxw pixels."""
    if d.textlength(text, font=f) <= maxw:
        return text
    while text and d.textlength(text + "…", font=f) > maxw:
        text = text[:-1]
    return text.rstrip() + "…"


def mmss(ms):
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


# ---- scrolling list ------------------------------------------------------------------------
class ListView:
    """A header + rows of (title, subtitle, payload), pre-rendered into one tall image."""

    def __init__(self, header, rows, back=False, actions=()):
        self.header, self.rows, self.back, self.actions = header, rows, back, actions
        self.off = 0.0
        self.img = self._render()

    def _render(self):
        h = max(LIST_H, HEAD_H + len(self.rows) * ROW_H + 24)
        im = Image.new("RGB", (W, h), (0, 0, 0)); d = ImageDraw.Draw(im)
        f_head, f_title, f_sub = font(24), font(19), font(15, bold=False)
        x = 22
        if self.back:
            d.text((x, 14), "‹", fill=GREY, font=font(28)); x += 26
        d.text((x, 14), fit(d, self.header, f_head, W - x - 20 - 185 * bool(self.actions)), fill=TEXT, font=f_head)
        for i, (label, _) in enumerate(self.actions):          # header buttons, right-aligned
            bx = W - 20 - (len(self.actions) - i) * 90
            d.rounded_rectangle([bx, 12, bx + 82, 44], 16, fill=GREEN if i == 0 else None,
                                outline=GREEN, width=2)
            f = font(14)
            d.text((bx + (82 - d.textlength(label, font=f)) / 2, 19), label,
                   fill=(0, 0, 0) if i == 0 else GREEN, font=f)
        for i, (title, sub, _) in enumerate(self.rows):
            y = HEAD_H + i * ROW_H
            d.text((22, y + 9), fit(d, title, f_title, W - 44), fill=TEXT, font=f_title)
            d.text((22, y + 35), fit(d, sub, f_sub, W - 44), fill=GREY, font=f_sub)
            d.line([22, y + ROW_H - 1, W - 22, y + ROW_H - 1], fill=(22, 22, 22))
        return to_rgbx(im)

    def scroll(self, dy):
        self.off = min(max(0.0, self.off - dy), float(self.img.shape[0] - LIST_H))

    def hit(self, y):
        """App-area y -> ('back' | ('action', i) | ('row', i) | None)."""
        yy = y + int(self.off)
        if yy < HEAD_H:
            return ("head", None)
        i = (yy - HEAD_H) // ROW_H
        return ("row", i) if 0 <= i < len(self.rows) else None

    def head_hit(self, x):
        for i in range(len(self.actions)):
            bx = W - 20 - (len(self.actions) - i) * 90
            if bx <= x <= bx + 82:
                return ("action", i)
        return ("back", None) if self.back and x < W / 2 else None

    def view(self, pressed_row):
        o = int(self.off)
        out = self.img[o:o + LIST_H].copy()
        if pressed_row is not None:
            y0 = HEAD_H + pressed_row * ROW_H - o
            a, b = max(0, y0), min(LIST_H, y0 + ROW_H - 1)
            if b > a:
                band = out[a:b]
                band[band[..., :3].max(-1) < 8] = (18, 40, 26, 0)
        return out


# ---- the app ------------------------------------------------------------------------------
class SpotifyApp(App):
    name = "Spotify"

    def __init__(self):
        self.state = "connecting"         # connecting | pair | login | player
        self.status = None                # last /status JSON (logged in)
        self.status_t = 0.0               # monotonic time of that status
        self.code = None                  # pairing code JSON
        self.library = None               # ListView of playlists
        self.library_t = -1e9
        self.tracks = None                # ListView of the open playlist (None = library shown)
        self.tracks_uri = None
        self.tracks_loading = False
        self.view_ver = 0                 # bumps when a ListView is replaced
        self.next_poll = 0.0
        self._busy = False
        self._started_service = False
        self.unreachable_since = None
        self.touch_st = None              # {y0, y, x0, drag, row, btn}
        self.btn = None                   # pressed panel button
        self.toast, self.toast_until = "", 0.0

    # ---- background ----
    def _poll(self):
        try:
            code, st = api("GET", "/status")
            if code == 0:
                self._unreachable()
                return
            self.unreachable_since = None
            if code == 204:                                   # no session: pairing or logging in
                c, auth = api("GET", "/auth/code")
                self.code = auth if c == 200 else None
                self.state = "pair" if self.code else "login"
                return
            self.status, self.status_t, self.state = st, time.monotonic(), "player"
            if self.library is None or time.monotonic() - self.library_t > LIBRARY_MAX_AGE:
                self._load_library()
            if self.tracks is not None and self.tracks_loading:
                self._load_tracks(self.tracks_uri, self.tracks.header)
        finally:
            self._busy = False

    def _unreachable(self):
        now = time.monotonic()
        if self.unreachable_since is None:
            self.unreachable_since = now
        self.state = "connecting"
        if not self._started_service and now - self.unreachable_since > 3:
            self._started_service = True                      # the service should be running; nudge it once
            subprocess.run(["rc-service", "spotify", "start"], capture_output=True, timeout=30)

    def _load_library(self):
        code, res = api("GET", "/library/playlists?limit=200", timeout=10)
        if code != 200:
            return
        user = (self.status or {}).get("username", "")
        rows = [("Liked Songs", "your liked songs", f"spotify:user:{user}:collection")]
        for p in res.get("items", []):
            owner = p.get("owner_username") or ""
            sub = f"{p.get('length', 0)} songs" + (f" · {owner}" if owner and owner != user else "")
            rows.append((p.get("name") or "(untitled)", sub, p["uri"]))
        rows.append(("Log out", "use a different Spotify account", "logout"))
        old = self.library
        self.library = ListView("Your Library", rows)
        if old is not None:
            self.library.off = min(old.off, float(self.library.img.shape[0] - LIST_H))
        self.library_t = time.monotonic()
        self.view_ver += 1

    def _load_tracks(self, uri, title):
        code, res = api("GET", "/context/tracks?uri=" + urllib.request.quote(uri, safe=""), timeout=10)
        if self.tracks_uri != uri:
            return                                            # user went back meanwhile
        if code != 200 or not res:
            self.tracks_loading = False
            self.toast_msg("couldn't load that playlist")
            return
        rows = []
        for item in res.get("tracks", []):
            t = item.get("track")
            if t:
                rows.append((t.get("name", "?"), ", ".join(t.get("artist_names", [])), item["uri"]))
            else:
                rows.append(("…", "loading", item["uri"]))
        self.tracks_loading = not res.get("ready") or res.get("cached", 0) < res.get("length", 0)
        if not rows:
            rows = [("loading…" if self.tracks_loading else "(empty)", "", None)]
        old_off = self.tracks.off if self.tracks is not None else 0.0
        self.tracks = ListView(title, rows, back=True, actions=(("Play", "play"), ("Shuffle", "shuffle")))
        self.tracks.off = min(old_off, float(self.tracks.img.shape[0] - LIST_H))
        self.view_ver += 1

    def _cmd(self, path, body=None, refresh=True):
        def run():
            api("POST", path, body)
            if refresh:
                self.next_poll = 0.0
        _bg(run)

    def _play(self, uri, skip_to=None, shuffle=False):
        def run():
            subprocess.run(["/usr/local/sbin/audio-speaker"], capture_output=True, timeout=10)
            api("POST", "/player/shuffle_context", {"shuffle_context": shuffle})
            body = {"uri": uri}
            if skip_to:
                body["skip_to_uri"] = skip_to
            code, _ = api("POST", "/player/play", body, timeout=10)
            if code != 200:
                self.toast_msg("couldn't play that")
            self.next_poll = 0.0
        _bg(run)
        self.toast_msg("starting…", 2.0)

    def _logout(self):
        def run():
            subprocess.run(["rc-service", "spotify", "stop"], capture_output=True, timeout=30)
            try:
                p = "/var/lib/go-librespot/state.json"
                with open(p) as f:
                    s = json.load(f)
                s.pop("credentials", None)
                with open(p, "w") as f:
                    json.dump(s, f)
            except (OSError, ValueError):
                pass
            subprocess.run(["rc-service", "spotify", "start"], capture_output=True, timeout=30)
            self.next_poll = 0.0
        self.library = self.tracks = self.status = None
        self.state = "login"
        _bg(run)

    def toast_msg(self, msg, secs=2.5):
        self.toast, self.toast_until = msg, time.monotonic() + secs

    # ---- now-playing helpers ----
    def _position(self):
        st = self.status or {}
        t = st.get("track")
        if not t:
            return 0, 0
        pos = t.get("position", 0)
        if not st.get("paused") and not st.get("stopped") and not st.get("buffering"):
            pos += (time.monotonic() - self.status_t) * 1000
        return min(pos, t.get("duration", 0)), t.get("duration", 0)

    # ---- App interface ----
    def key(self, now):
        mono = time.monotonic()
        if not self._busy and mono >= self.next_poll:
            self._busy = True
            self.next_poll = mono + (TRACKS_POLL if self.tracks is not None and self.tracks_loading else POLL_EVERY)
            _bg(self._poll)
        if self.state != "player":
            return (self.state, self.code and self.code.get("code"))
        st = self.status or {}
        t = st.get("track") or {}
        pos, _ = self._position()
        ts = self.touch_st
        lv = self.tracks or self.library
        return ("player", self.view_ver, lv.off if lv else 0, ts and ts.get("row"), self.btn,
                t.get("uri"), st.get("paused"), st.get("volume"), int(pos // 1000),
                self.toast if mono < self.toast_until else "")

    def render(self, now):
        if self.state == "pair":
            return self._render_pair()
        if self.state != "player":
            msg = {"connecting": "starting Spotify…", "login": "logging in…"}[self.state]
            im, d = canvas(APP_H)
            centre_text(d, APP_H // 2 - 40, msg, font(24), GREEN)
            return to_rgbx(im)
        out = np.zeros((APP_H, W, 4), np.uint8)
        lv = self.tracks or self.library
        if lv is not None:
            ts = self.touch_st
            out[:LIST_H] = lv.view(ts.get("row") if ts and not ts["drag"] else None)
        else:
            im, d = canvas(LIST_H)
            centre_text(d, LIST_H // 2 - 20, "loading your library…", font(20), GREY)
            out[:LIST_H] = to_rgbx(im)
        out[LIST_H:] = self._render_panel()
        return out

    def _render_pair(self):
        im, d = canvas(APP_H)
        centre_text(d, 40, "Log in to Spotify", font(30), GREEN)
        f = font(19, bold=False)
        centre_text(d, 120, "On your phone or computer, go to", f, TEXT)
        centre_text(d, 156, "spotify.com/pair", font(30), ACCENT)
        centre_text(d, 214, "and enter this code:", f, TEXT)
        code = (self.code or {}).get("code", "")
        fc = font(56)
        spaced = " ".join(code)
        bw = d.textlength(spaced, font=fc) + 60
        d.rounded_rectangle([(W - bw) / 2, 262, (W + bw) / 2, 362], 18, outline=GREEN, width=3)
        centre_text(d, 280, spaced, fc, TEXT)
        centre_text(d, 410, "The phone logs in by itself once", font(16, bold=False), GREY)
        centre_text(d, 434, "you approve it. You only do this once.", font(16, bold=False), GREY)
        centre_text(d, 500, "waiting for approval…", font(18), DIM)
        return to_rgbx(im)

    # panel geometry (app-area coords)
    def _buttons(self):
        cy = LIST_H + 154
        return {"prev": (W // 2 - 100, cy, 30), "play": (W // 2, cy, 36), "next": (W // 2 + 100, cy, 30),
                "vol-": (46, cy, 26), "vol+": (W - 46, cy, 26)}

    def _render_panel(self):
        im, d = canvas(PANEL_H)
        d.line([0, 0, W, 0], fill=(30, 60, 40), width=2)
        st = self.status or {}
        t = st.get("track")
        if t:
            d.text((22, 14), fit(d, t.get("name", ""), font(21), W - 44), fill=TEXT, font=font(21))
            sub = ", ".join(t.get("artist_names", []))
            d.text((22, 44), fit(d, sub, font(16, bold=False), W - 44), fill=GREY, font=font(16, bold=False))
            pos, dur = self._position()
            x0, x1, y = 22, W - 22, 84
            d.rounded_rectangle([x0, y, x1, y + 5], 3, fill=(45, 45, 45))
            if dur:
                d.rounded_rectangle([x0, y, x0 + (x1 - x0) * pos / dur, y + 5], 3, fill=GREEN)
            fs = font(13, bold=False)
            d.text((x0, y + 10), mmss(pos), fill=GREY, font=fs)
            d.text((x1 - d.textlength(mmss(dur), font=fs), y + 10), mmss(dur), fill=GREY, font=fs)
        else:
            centre_text(d, 30, "nothing playing", font(20), GREY)
            centre_text(d, 62, "tap a playlist to start", font(15, bold=False), DIM)
        toast = self.toast if time.monotonic() < self.toast_until else ""
        if toast:
            centre_text(d, 98, toast, font(14), GREEN)
        for name, (cx, cy, r) in self._buttons().items():
            self._draw_button(d, name, cx, cy - LIST_H, r, self.btn == name, st)
        vol, steps = st.get("volume"), st.get("volume_steps") or 100
        if vol is not None:
            label = f"vol {round(100 * vol / steps)}%"
            d.text((W - 46 - d.textlength(label, font=font(12)) / 2, 182), label, fill=DIM, font=font(12))
        return to_rgbx(im)

    @staticmethod
    def _draw_button(d, name, cx, cy, r, pressed, st):
        if name == "play":
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(120, 255, 170) if pressed else GREEN)
            if st.get("paused") or st.get("stopped") or not st.get("track"):
                d.polygon([(cx - 10, cy - 15), (cx - 10, cy + 15), (cx + 16, cy)], fill=(0, 0, 0))
            else:
                d.rectangle([cx - 11, cy - 14, cx - 4, cy + 14], fill=(0, 0, 0))
                d.rectangle([cx + 4, cy - 14, cx + 11, cy + 14], fill=(0, 0, 0))
            return
        col = GREEN if pressed else TEXT
        if pressed:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(20, 45, 30))
        if name in ("prev", "next"):
            s = 1 if name == "next" else -1
            d.polygon([(cx - 9 * s, cy - 12), (cx - 9 * s, cy + 12), (cx + 7 * s, cy)], fill=col)
            bx = cx + 10 * s                                  # the bar the triangle points at
            d.rectangle([bx - 2, cy - 12, bx + 2, cy + 12], fill=col)
        else:                                                 # speaker with - / +
            d.polygon([(cx - 14, cy - 5), (cx - 8, cy - 5), (cx - 1, cy - 11), (cx - 1, cy + 11),
                       (cx - 8, cy + 5), (cx - 14, cy + 5)], fill=col)
            d.line([cx + 5, cy, cx + 15, cy], fill=col, width=3)
            if name == "vol+":
                d.line([cx + 10, cy - 5, cx + 10, cy + 5], fill=col, width=3)

    def _button_at(self, x, y):
        for name, (cx, cy, r) in self._buttons().items():
            if (x - cx) ** 2 + (y - cy) ** 2 <= (r + 14) ** 2:
                return name
        return None

    def touch(self, ev, x, y):
        if self.state != "player":
            return
        y -= TOP                                              # app-area coords
        lv = self.tracks or self.library
        if ev == "down":
            self.touch_st = {"x0": x, "y0": y, "y": y, "drag": False, "row": None}
            if y >= LIST_H:
                self.btn = self._button_at(x, y)
            elif lv is not None:
                h = lv.hit(y)
                if h and h[0] == "row":
                    self.touch_st["row"] = h[1]
        elif ev == "move" and self.touch_st:
            ts = self.touch_st
            if ts["y0"] < LIST_H and lv is not None:
                if not ts["drag"] and abs(y - ts["y0"]) > DRAG_START:
                    ts["drag"], ts["row"] = True, None
                if ts["drag"]:
                    lv.scroll(y - ts["y"])
            ts["y"] = y
        elif ev == "up" and self.touch_st:
            ts, self.touch_st = self.touch_st, None
            btn, self.btn = self.btn, None
            if ts["drag"]:
                return
            if ts["y0"] >= LIST_H:
                if btn and btn == self._button_at(x, y):
                    self._press(btn)
                return
            if lv is None:
                return
            h = lv.hit(y)
            if h is None:
                return
            if h[0] == "head":
                hh = lv.head_hit(x)
                if hh and hh[0] == "back":
                    self.tracks = self.tracks_uri = None
                    self.view_ver += 1
                elif hh and hh[0] == "action" and self.tracks is not None:
                    self._play(self.tracks_uri, shuffle=lv.actions[hh[1]][1] == "shuffle")
            elif h[0] == "row" and h[1] == ts["row"]:
                self._open_row(lv, h[1])

    def _open_row(self, lv, i):
        title, _, payload = lv.rows[i]
        if lv is self.library:
            if payload == "logout":
                self._logout()
                return
            self.tracks_uri, self.tracks_loading = payload, True
            self.tracks = ListView(title, [("loading…", "", None)], back=True,
                                   actions=(("Play", "play"), ("Shuffle", "shuffle")))
            self.view_ver += 1
            self.next_poll = 0.0
            _bg(self._load_tracks, payload, title)
        elif payload:
            self._play(self.tracks_uri, skip_to=payload)

    def _press(self, btn):
        st = self.status or {}
        if btn == "play":
            if st.get("track"):
                st["track"]["position"] = self._position()[0]  # optimistic: flip the icon now
                st["paused"] = not st.get("paused")
                self.status_t = time.monotonic()
                self._cmd("/player/playpause")
        elif btn == "next":
            self._cmd("/player/next")
        elif btn == "prev":
            self._cmd("/player/prev")
        elif btn in ("vol-", "vol+"):
            steps = st.get("volume_steps") or 100
            delta = steps // 10 * (1 if btn == "vol+" else -1)
            if st.get("volume") is not None:
                st["volume"] = max(0, min(steps, st["volume"] + delta))
            self._cmd("/player/volume", {"volume": delta, "relative": True})
