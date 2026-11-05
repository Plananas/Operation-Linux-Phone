"""Tests for the on-screen keyboard and the two-finger input under it. Needs PIL, numpy and libtrend, so run it on the phone:
    tar -C overlay/usr/local/lib/trendos -cf - tos | ssh root@192.168.42.129 'rm -rf /tmp/kbt; mkdir /tmp/kbt; tar -C /tmp/kbt -xf -'
    ssh root@192.168.42.129 'TOS_PATH=/tmp/kbt python3 -I -' < tools/phone/test_keyboard.py
It uses TOS_PATH, or the installed shell's code. It doesn't touch the running shell.
"""
import os, struct, sys

sys.path.insert(0, os.environ.get("TOS_PATH", "/usr/local/lib/trendos"))
from tos.hw.inputdev import EV_FMT, Input
from tos.keyboard import GAP, KB_Y, KH, Keyboard, build_rows, nearest_key
from tos.apps.web.app import is_address, lower_scheme

checks = failures = 0


def check(cond, what):
    global checks, failures
    checks += 1
    if not cond:
        failures += 1
        print("FAIL", what)


def equal(got, want, what=""):
    check(got == want, f"{what}: got {got!r}, want {want!r}")


class Typing:
    """A keyboard with a clock that only moves when told, which types by label."""

    def __init__(self, **kw):
        self.now = 100.0
        self.done, self.cancelled = [], []
        self.kb = Keyboard(on_done=self.done.append, on_cancel=lambda: self.cancelled.append(1), **kw)

    def at(self, label):
        for row in self.kb._layout():
            for k in row:
                if k[0] == label:
                    return k[1] + k[3] // 2, k[2] + k[4] // 2
        raise KeyError(label)

    def ev(self, kind, x, y, finger=0):
        self.kb.touch(kind, x, y, finger=finger, now=self.now)

    def press(self, label, finger=0):
        self.ev("down", *self.at(label), finger)

    def lift(self, label, finger=0):
        self.ev("up", *self.at(label), finger)

    def tap(self, *labels, gap=1.0):
        for label in labels:
            self.press(label)
            self.lift(label)
            self.now += gap

    def type(self, text, gap=1.0):
        self.tap(*text, gap=gap)


def test_rollover():
    t = Typing()
    t.press("a"); t.press("b", 1)
    equal(t.kb.text, "a", "second finger types the first")
    t.lift("a")
    equal(t.kb.text, "a", "lifting a typed key does nothing more")
    t.press("c")                             # the first finger's slot is free again; the second is still down
    equal(t.kb.text, "ab", "third press types the second")
    t.lift("b", 1); t.lift("c")
    equal(t.kb.text, "abc", "every letter, in order")


def test_gaps_and_edges():
    rows = build_rows("abc")
    a, b = rows[0][0], rows[0][1]            # q, w
    equal(nearest_key(rows, a[1] + a[3] + 1, a[2] + 10), "q", "left of the gap")
    equal(nearest_key(rows, b[1] - 1, a[2] + 10), "w", "right of the gap")
    equal(nearest_key(rows, 0, a[2] + 10), "q", "left edge")
    equal(nearest_key(rows, 479, a[2] + 10), "p", "right edge")
    equal(nearest_key(rows, a[1] + 5, KB_Y), "q", "top edge")
    equal(nearest_key(rows, 240, 799), "space", "bottom edge")
    for y in range(KB_Y, 800):               # no dead pixels, in any layer
        for x in range(0, 480, 3):
            for layer in ("abc", "123", "#+="):
                check(nearest_key(build_rows(layer), x, y), f"{layer} {x},{y}")
    t = Typing()
    x = t.at("q")[0]
    t.ev("down", x, a[2] + KH + GAP // 2 - 1)
    t.ev("up", x, a[2] + KH + GAP // 2 - 1)
    equal(t.kb.text, "q", "a tap in the gap between rows types")


def test_rolling_and_sliding():
    t = Typing()
    x, y = t.at("g")
    t.ev("down", x, y); t.ev("move", x + 28, y + 3); t.ev("up", x + 28, y + 3)      # past its edge, within SLIDE
    equal(t.kb.text, "g", "a small roll keeps the key")
    t = Typing()
    t.press("g")
    x, y = t.at("k")
    t.ev("move", x, y); t.ev("up", x, y)
    equal(t.kb.text, "k", "a clear slide changes the key")
    t = Typing()
    x, y = t.at("q")
    t.ev("down", x, y); t.ev("move", x, KB_Y - 40); t.ev("up", x, KB_Y - 40)
    equal(t.kb.text, "", "sliding off the top types nothing")
    t = Typing()
    t.ev("down", 240, KB_Y - 10); t.ev("up", 240, KB_Y - 10)
    equal(t.kb.text, "", "a touch above the keyboard types nothing")


def test_shift():
    t = Typing()
    t.tap("shift"); t.type("ab")
    equal(t.kb.text, "Ab", "shift lasts one letter")
    equal(t.kb.shift, "off")
    t = Typing()
    t.tap("shift"); t.now += 0.2 - 1.0 + 0.0; t.tap("shift"); t.type("ab")
    equal(t.kb.text, "AB", "double tap locks")
    t.tap("shift"); t.type("c")
    equal(t.kb.text, "ABc", "another tap unlocks")
    t = Typing()
    t.press("shift"); t.press("a", 1); t.lift("a", 1); t.lift("shift")
    equal(t.kb.text, "A", "shift held while typing")


def test_prose():
    t = Typing(prose=True)
    t.type("hi")
    t.tap(".", "space"); t.type("ok")
    equal(t.kb.text, "Hi. Ok", "sentences start with a capital")
    t = Typing(prose=True)
    t.tap("h", "i", "space", gap=0.2); t.tap("space")
    equal(t.kb.text, "Hi. ", "double space")
    equal(t.kb.shift, "auto", "and the next sentence gets a capital")
    t.tap("del")
    equal(t.kb.shift, "off", "the capital goes when it stops being a sentence start")
    t = Typing(prose=True)
    t.tap("shift")
    equal(t.kb.shift, "off", "shift turns the automatic capital off")
    t.type("a")
    equal(t.kb.text, "a")
    for kw in ({}, {"prose": False}):
        t = Typing(**kw)
        equal(t.kb.shift, "off", "exact text starts lower case")
        t.tap("a", "space", gap=0.2); t.tap("space")
        equal(t.kb.text, "a  ", "exact text keeps double spaces")


def test_layers():
    t = Typing(prose=True)
    t.tap("123"); t.type("10:30")
    equal(t.kb.text, "10:30")
    equal(t.kb.layer, "123", "numbers and their punctuation stay on the layer")
    t.tap("space")
    equal(t.kb.layer, "abc", "space goes back to letters")
    t = Typing(prose=True)
    t.kb.shift = "off"
    t.type("a"); t.tap("123", "@")
    equal(t.kb.layer, "abc", "a symbol goes back to letters")
    equal(t.kb.text, "a@")
    t = Typing()
    t.tap("123", "@")
    equal(t.kb.layer, "123", "exact text stays on the layer")
    t = Typing()
    t.tap(",", ".")
    equal(t.kb.text, ",.", "comma and full stop are on the letters layer")
    for layer in ("abc", "123", "#+="):
        labels = [k[0] for row in build_rows(layer) for k in row]
        i = labels.index("space")
        check("esc" not in labels[i - 1:i + 2], f"esc isn't next to space on {layer}")


def test_delete():
    t = Typing(text="one two three")
    t.tap("del")
    equal(t.kb.text, "one two thre", "a tap deletes one")
    t = Typing(text="abcdefgh")
    t.press("del")
    t.kb.key(t.now + 0.1)
    equal(t.kb.text, "abcdefgh", "nothing before the hold")
    for i in range(3):
        t.now += 0.4 if i == 0 else 0.08
        t.kb.key(t.now)
    equal(t.kb.text, "abcde", "holding repeats")
    t.lift("del")
    equal(t.kb.text, "abcde", "lifting after a repeat deletes no more")
    t = Typing(text="alpha beta gamma delta epsilon zeta")
    t.press("del")
    t.now += 0.4
    t.kb.key(t.now)
    for _ in range(11):
        t.now += 0.08
        t.kb.key(t.now)
    equal(t.kb.text, "alpha beta gamma delta epsilon zeta"[:-12], "characters first")
    t.now += 0.08
    t.kb.key(t.now)
    equal(t.kb.text, "alpha beta gamma ", "then whole words")
    t = Typing(text="abc")
    calls = []
    t.kb.on_change = lambda: calls.append(t.kb.text)
    t.press("del"); t.now += 0.5; t.kb.key(t.now)
    equal(calls, ["ab"], "the host hears about a repeat")
    t = Typing(text="abc")
    t.press("del"); t.now += 0.5; t.kb.key(t.now)
    t.press("x", 1); t.now += 0.5; t.kb.key(t.now)
    equal(t.kb.text, "ab", "another finger landing stops the repeat")
    t.kb.key(t.now + 5)
    equal(t.kb.text, "ab")


def test_esc_and_done():
    t = Typing()
    t.tap("esc")
    equal(t.cancelled, [1], "with nothing typed, esc just closes")
    t = Typing(text="a long message")
    t.tap("esc")
    equal(t.cancelled, [], "one tap doesn't throw text away")
    check(t.kb.esc_until, "it asks")
    check("sure?" == t.kb._disp("esc", True), "the label asks")
    t.now = t.kb.esc_until - 0.5
    t.tap("esc")
    equal(t.cancelled, [1], "a second tap does")
    t = Typing(text="a")
    t.tap("esc")
    t.now += 3
    t.kb.key(t.now)
    check(not t.kb.esc_until, "the question expires")
    t.tap("esc")
    equal(t.cancelled, [], "and the next tap only asks again")
    t = Typing(text="a")
    t.tap("esc"); t.tap("b")
    check(not t.kb.esc_until, "typing cancels the question")
    t = Typing(text="hi")
    t.press("done"); t.press("a", 1)
    equal(t.done, [], "done waits while it's held")
    t.lift("done")
    equal(t.done, [], "and until every finger is up, or the app gets the rest of the touch")
    t.lift("a", 1)
    equal(t.done, ["hia"], "with what the other finger typed")
    t = Typing(text="hi")
    t.press("done"); t.press("a", 1)
    t.lift("done")
    t.ev("move", 240, KB_Y - 50, 1); t.ev("up", 240, KB_Y - 50, 1)
    equal(t.done, ["hi"], "a finger sliding off the keyboard types nothing, and done still happens")
    t = Typing(text="hi")
    t.press("x"); t.press("done", 1); t.lift("done", 1); t.lift("x")
    equal(t.done, ["hix"], "the last key goes in before done")


def test_render():
    t = Typing()
    equal(t.kb.render().shape, (KH * 4 + GAP * 5, 480, 4), "size")
    plain = t.kb.render().tobytes()
    t.press("a"); t.press("b", 1)
    pressed = t.kb.render()
    check(pressed.tobytes() != plain, "pressed keys show")
    t.lift("a"); t.lift("b", 1)
    equal(t.kb.render().tobytes(), plain, "and stop showing")
    t = Typing(text="a")
    base = t.kb.render().tobytes()
    t.tap("esc")
    armed = t.kb.render().tobytes()
    check(armed != base, "esc asks visibly")
    t.tap("b")
    t.kb.text = "a"
    equal(t.kb.render().tobytes(), base, "the base image isn't left armed")
    t = Typing(prose=True)
    k1 = t.kb.key(t.now)
    t.press("a")
    check(t.kb.key(t.now) != k1, "a press changes the redraw key")


def test_web_addresses():
    check(is_address("Https://example.com/Path"), "a capitalised scheme is an address")
    check(is_address("Www.example.com"), "so is a capitalised host")
    check(not is_address("What is 2.5 plus 3"), "a question isn't")
    equal(lower_scheme("Https://example.com/Path"), "https://example.com/Path", "only the scheme changes")
    equal(lower_scheme("Www.Example.com/Path"), "Www.Example.com/Path")


# ---- the input device ------------------------------------------------------------------------------------------
SLOT, TRACK, X, Y, SYN, ABS = 0x2F, 0x39, 0x35, 0x36, 0, 3


def raw(*events):
    return b"".join(struct.pack(EV_FMT, 0, 0, t, c, v) for t, c, v in events)


def poll(inp, *events):
    r, w = os.pipe()
    os.set_blocking(r, False)
    os.write(w, raw(*events))
    for fd in inp.fds:
        os.close(fd)
    inp.fds = [r]
    got = [e[:3] for e in inp.poll()]
    os.close(w)
    return got


def syn():
    return (0, 0, 0)


def contact(slot, tid, x, y):
    return [(ABS, SLOT, slot), (ABS, TRACK, tid), (ABS, X, x), (ABS, Y, y), syn()]


def lift(slot):
    return [(ABS, SLOT, slot), (ABS, TRACK, -1), syn()]


def test_input():
    inp = Input()
    equal(poll(inp, *contact(0, 5, 10, 20)), [("down", 10, 20)], "first finger down")
    equal(poll(inp, *contact(1, 6, 30, 40)), [("down2", 30, 40), ("move", 10, 20)], "second finger down")
    equal(poll(inp, (ABS, X, 33), syn()), [("move", 10, 20), ("move2", 33, 40)], "second finger moves")
    equal(poll(inp, *lift(0)), [("up", 10, 20)], "first finger up, second down")
    equal(poll(inp, *contact(0, 7, 50, 60)), [("down", 50, 60)], "a new first finger, second still down")
    equal(poll(inp, *lift(1)), [("up2", 33, 40), ("move", 50, 60)], "second finger up")
    equal(poll(inp, *lift(0)), [("up", 50, 60)], "all up")
    equal(poll(inp, *contact(2, 9, 70, 80)), [], "a third finger is ignored")
    equal(poll(inp, *lift(2)), [], "both ways")

    inp = Input()
    both = [(ABS, SLOT, 1), (ABS, TRACK, 2), (ABS, X, 1), (ABS, Y, 1), (ABS, SLOT, 0), (ABS, TRACK, 3), (ABS, X, 2), (ABS, Y, 2), syn()]
    equal(poll(inp, *both), [("down", 2, 2), ("down2", 1, 1)], "both in one report")
    swap = [(ABS, SLOT, 0), (ABS, TRACK, -1), (ABS, SLOT, 1), (ABS, TRACK, -1), (ABS, TRACK, 8), (ABS, X, 5), syn()]
    equal(poll(inp, *swap), [("up", 2, 2), ("up2", 1, 1), ("down2", 5, 1)], "lifts come before presses")

    inp = Input()
    poll(inp, *contact(0, 5, 10, 20))
    equal(poll(inp, (ABS, TRACK, 6), (ABS, X, 90), (ABS, Y, 91), syn()), [("up", 10, 20), ("down", 90, 91)],
          "a new contact replacing the old one is a lift and a press, as in a fast double letter")


for test in (test_rollover, test_gaps_and_edges, test_rolling_and_sliding, test_shift, test_prose, test_layers, test_delete,
             test_esc_and_done, test_render, test_web_addresses, test_input):
    test()
print(f"{checks} checks, {failures} failures")
sys.exit(1 if failures else 0)
