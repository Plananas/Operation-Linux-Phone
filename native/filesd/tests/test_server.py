#!/usr/bin/env python3
"""Runs the real filesd against temporary folders and attacks it over real sockets.
Usage: test_server.py path/to/filesd
Everything that matters about access control is checked here."""
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

BIN = sys.argv[1]
PORT = 18733
checks = failures = 0


def check(cond, what):
    global checks, failures
    checks += 1
    if not cond:
        failures += 1
        print("FAIL", what)


def raw(data, port=PORT, wait=5.0):
    """Send bytes, return everything that comes back as (status, headers, body)."""
    with socket.create_connection(("127.0.0.1", port), timeout=wait) as s:
        s.sendall(data)
        got = b""
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                got += chunk
        except (socket.timeout, ConnectionResetError):
            pass
    head, _, body = got.partition(b"\r\n\r\n")
    m = re.match(rb"HTTP/1\.1 (\d+)", head)
    return int(m.group(1)) if m else 0, head.decode("latin-1"), body


def req(method, path, body=b"", cookie=None, marker=True, extra=""):
    h = f"{method} {path} HTTP/1.1\r\nHost: x\r\n"
    if marker:
        h += "X-Trend: 1\r\n"
    if cookie:
        h += f"Cookie: trend_session={cookie}\r\n"
    if body or method in ("PUT", "POST"):
        h += f"Content-Length: {len(body)}\r\n"
    return raw((h + extra + "\r\n").encode("latin-1") + body)


def start(work, *args):
    out = open(os.path.join(work, "status"), "wb")
    p = subprocess.Popen([BIN, "-p", str(PORT), "-w", os.path.join(work, "page.html"), "-f", os.path.join(work, "f.ttf"),
                          "-t", os.path.join(work, "tmp"), f"music={work}/music", f"files={work}/files", *args], stdout=out)
    path = os.path.join(work, "status")
    for _ in range(100):
        time.sleep(0.05)
        text = open(path).read()
        if "U " in text:
            return p, re.search(r"U (\d{6}) ", text).group(1)
    raise SystemExit("server did not start")


def stop(p):
    p.send_signal(signal.SIGTERM)
    check(p.wait(timeout=5) == 0, "stops cleanly on SIGTERM")


work = tempfile.mkdtemp(prefix="filesd-test-")
try:
    with open(f"{work}/page.html", "w") as f:
        f.write("<html>page</html>")
    with open(f"{work}/f.ttf", "wb") as f:
        f.write(b"FONT")
    with open(f"{work}/secret.txt", "w") as f:
        f.write("TOP-SECRET")
    p, pin = start(work)

    # --- no way in without the PIN ---
    st, head, body = req("GET", "/")
    check(st == 200 and body == b"<html>page</html>", "page is public")
    check("frame-ancestors 'none'" in head and "nosniff" in head, "page has its security headers")
    check(req("GET", "/vt323.ttf")[2] == b"FONT", "font is public")
    for method, path in (("GET", "/api/list"), ("GET", "/api/list/music"), ("GET", "/api/file/music/a"),
                         ("PUT", "/api/file/music/a"), ("DELETE", "/api/file/music/a"), ("POST", "/api/dir/music/a")):
        check(req(method, path)[0] == 401, f"{method} {path} needs a session")
    check(req("GET", "/api/list", cookie="0" * 32)[0] == 401, "a made-up session is refused")
    check(req("GET", "/api/list", cookie="")[0] == 401, "an empty session is refused")
    check(req("POST", "/api/login", b"000000", marker=False)[0] == 403, "login needs the marker header")

    wrong = "000000" if pin != "000000" else "111111"
    check(req("POST", "/api/login", wrong.encode())[0] == 403, "wrong PIN refused")
    check(req("POST", "/api/login", (pin + "0").encode())[0] == 403, "PIN with extra digit refused")
    check(req("POST", "/api/login", pin[:5].encode())[0] == 403, "partial PIN refused")
    st, head, _ = req("POST", "/api/login", pin.encode())
    check(st == 200, "right PIN accepted")
    check("HttpOnly" in head and "SameSite=Strict" in head, "cookie is locked down")
    tok = re.search(r"trend_session=([0-9a-f]{32})", head).group(1)

    # --- ordinary use ---
    st, _, body = req("GET", "/api/list", cookie=tok)
    check(st == 200 and b'"music"' in body and b'"files"' in body, "lists the shared folders")
    check(req("PUT", "/api/file/music/a%20b.mp3", b"hello", marker=False, cookie=tok)[0] == 403, "upload needs the marker header")
    check(req("PUT", "/api/file/music/a%20b.mp3", b"hello", cookie=tok)[0] == 201, "upload")
    check(open(f"{work}/music/a b.mp3", "rb").read() == b"hello", "upload landed in the folder")
    st, head, body = req("GET", "/api/file/music/a%20b.mp3", cookie=tok)
    check(st == 200 and body == b"hello", "download")
    check("attachment" in head and "sandbox" in head and "a%20b.mp3" in head, "download can't run as a page")
    st, head, body = req("GET", "/api/file/music/a%20b.mp3", cookie=tok, extra="Range: bytes=1-2\r\n")
    check(st == 206 and body == b"el" and "bytes 1-2/5" in head, "partial download")
    check(req("GET", "/api/file/music/a%20b.mp3", cookie=tok, extra="Range: bytes=9-\r\n")[0] == 416, "impossible range")
    check(req("PUT", "/api/file/music/a%20b.mp3", b"second", cookie=tok)[0] == 201, "upload over a file replaces it")
    check(open(f"{work}/music/a b.mp3", "rb").read() == b"second", "replacement took effect")
    check(req("POST", "/api/dir/files/sub", cookie=tok)[0] == 201, "new folder")
    check(req("POST", "/api/dir/files/sub", cookie=tok)[0] == 409, "new folder that already exists")
    check(req("PUT", "/api/file/files/sub/n.txt", b"x", cookie=tok)[0] == 201, "upload to a subfolder")
    check(req("PUT", "/api/file/files/sub", b"x", cookie=tok)[0] == 409, "upload can't replace a folder")
    check(req("DELETE", "/api/file/files/sub", cookie=tok)[0] == 409, "can't delete a folder that isn't empty")
    check(req("DELETE", "/api/file/files/sub/n.txt", cookie=tok)[0] == 200, "delete a file")
    check(req("DELETE", "/api/file/files/sub", cookie=tok)[0] == 200, "delete an empty folder")
    check(not os.path.exists(f"{work}/files/sub"), "the folder really went")
    check(req("DELETE", "/api/file/music", cookie=tok)[0] == 400, "a shared folder itself can't be deleted")

    # a 3 MB upload, with the body sent separately and an Expect header, as curl does
    blob = os.urandom(3 << 20)
    with socket.create_connection(("127.0.0.1", PORT), timeout=10) as s:
        s.sendall(f"PUT /api/file/files/big.bin HTTP/1.1\r\nX-Trend: 1\r\nCookie: trend_session={tok}\r\n"
                  f"Content-Length: {len(blob)}\r\nExpect: 100-continue\r\n\r\n".encode())
        check(s.recv(100).startswith(b"HTTP/1.1 100"), "answers Expect: 100-continue")
        s.sendall(blob)
        check(b" 201 " in s.recv(200), "large upload accepted")
    check(open(f"{work}/files/big.bin", "rb").read() == blob, "large upload is intact")
    check(req("GET", "/api/file/files/big.bin", cookie=tok)[2] == blob, "large download is intact")

    # an upload cut off half way leaves nothing behind
    with socket.create_connection(("127.0.0.1", PORT), timeout=5) as s:
        s.sendall(f"PUT /api/file/files/cut.bin HTTP/1.1\r\nX-Trend: 1\r\nCookie: trend_session={tok}\r\n"
                  f"Content-Length: 1000\r\n\r\nonly-this".encode())
    time.sleep(0.3)
    check(not os.path.exists(f"{work}/files/cut.bin"), "a broken upload never appears")
    check(os.listdir(f"{work}/tmp") == [], "a broken upload leaves no temporary file")

    # --- climbing out of the shared folders ---
    os.symlink(f"{work}/secret.txt", f"{work}/music/link.txt")
    os.symlink(work, f"{work}/music/linkdir")
    os.mkfifo(f"{work}/music/pipe")
    with open(f"{work}/music/.hidden", "w") as f:
        f.write("hidden")
    for path in ("../secret.txt", "music/../../secret.txt", "music/%2e%2e/%2e%2e/secret.txt",
                 "music/..%2f..%2fsecret.txt", "music/%2e%2e%2f%2e%2e%2fsecret.txt", "music%2f..%2f..%2fsecret.txt",
                 "music/..%5c..%5csecret.txt", "music//secret.txt", "/etc/passwd", "%2fetc%2fpasswd",
                 "music/link.txt", "music/linkdir/secret.txt", "music/.hidden", "music/pipe",
                 "secret.txt", "tmp/x", "music/%00", "music/a%0ab", "music/%ff"):
        st, _, body = req("GET", "/api/file/" + path, cookie=tok)
        check(st in (400, 404) and b"SECRET" not in body and b"hidden" not in body, f"GET {path} stays inside ({st})")
        before = open(f"{work}/secret.txt").read()
        st = req("PUT", "/api/file/" + path, b"PWNED", cookie=tok)[0]
        check(st in (201, 400, 404, 409), f"PUT {path} answered ({st})")
        check(open(f"{work}/secret.txt").read() == before, f"PUT {path} left the outside alone")
        st = req("DELETE", "/api/file/" + path, cookie=tok)[0]
    check(os.path.exists(f"{work}/secret.txt"), "nothing outside was deleted")
    st, _, body = req("GET", "/api/list/music/linkdir", cookie=tok)
    check(st == 404, "can't list through a symlink")
    st, _, body = req("GET", "/api/list/music", cookie=tok)
    check(b"link.txt" not in body and b"pipe" not in body and b".hidden" not in body, "listing hides what can't be served")
    check(req("GET", "/api/list/..", cookie=tok)[0] == 400, "can't list above the top")

    # listing the same folder twice, and at the same time, sees the same thing each time
    first = req("GET", "/api/list/music", cookie=tok)[2]
    check(b"a b.mp3" in first, "a shared folder lists its files")
    check(req("GET", "/api/list/music", cookie=tok)[2] == first, "and lists them again")
    with ThreadPoolExecutor(8) as pool:
        same = list(pool.map(lambda _: req("GET", "/api/list/music", cookie=tok)[2], range(8)))
    check(all(body == first for body in same), "and lists them the same when asked at once")

    # a name that needs escaping comes back as valid JSON and doesn't break out of it
    check(req("PUT", '/api/file/files/%22%3Cb%3E.txt', b"x", cookie=tok)[0] == 201, "odd name accepted")
    import json
    names = [e["name"] for e in json.loads(req("GET", "/api/list/files", cookie=tok)[2])["entries"]]
    check('"<b>.txt' in names, "odd name survives the JSON")

    # --- hostile requests ---
    check(raw(b"GET / HTTP/1.1\r\n" + b"A: " + b"x" * 20000 + b"\r\n\r\n")[0] == 431, "giant headers are refused")
    check(raw(b"\x00\xff garbage\r\n\r\n")[0] == 400, "garbage is refused")
    check(raw(b"PUT /api/file/files/x HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n")[0] == 400, "chunked is refused")
    st = raw(f"PUT /api/file/files/huge HTTP/1.1\r\nX-Trend: 1\r\nCookie: trend_session={tok}\r\nContent-Length: 9000000000000000\r\n\r\n".encode())[0]
    check(st == 507, "more than the disk can hold is refused up front")
    st = raw(f"PUT /api/file/files/nolen HTTP/1.1\r\nX-Trend: 1\r\nCookie: trend_session={tok}\r\n\r\n".encode())[0]
    check(st == 411, "an upload with no length is refused")
    check(req("PATCH", "/api/file/files/x", cookie=tok)[0] == 404, "unknown method")

    # many at once, all served, nothing corrupted
    socks = [socket.create_connection(("127.0.0.1", PORT), timeout=10) for _ in range(40)]
    for s in socks:
        s.close()
    time.sleep(0.2)
    check(req("GET", "/api/list", cookie=tok)[0] == 200, "still healthy after a burst of connections")

    # status lines, for the shell
    time.sleep(0.8)
    status = open(f"{work}/status", errors="replace").read()
    check(re.search(rf"^U {pin} {PORT}$", status, re.M), "reports the PIN and port")
    check(re.search(r"^F \d+$", status, re.M), "reports free space")
    check(re.search(r"^T \d u k \d+ \d+ .+$", status, re.M), "reports a finished upload")
    check(re.search(r"^T \d d k \d+ \d+ .+$", status, re.M), "reports a finished download")
    check(re.search(r"^T \d u x \d+ 1000 cut\.bin$", status, re.M), "reports a failed upload")
    stop(p)

    # --- a new start means a new PIN, and old sessions are dead ---
    p, pin2 = start(work)
    check(req("GET", "/api/list", cookie=tok)[0] == 401, "a session doesn't survive a restart")

    # --- ten wrong guesses and it stops ---
    wrong = "000000" if pin2 != "000000" else "111111"
    for i in range(9):
        check(req("POST", "/api/login", wrong.encode())[0] == 403, "wrong PIN")
    check(p.poll() is None, "still running after nine wrong guesses")
    check(b"Too many" in req("POST", "/api/login", wrong.encode())[2], "the tenth says so")
    check(p.wait(timeout=5) == 0, "and the server stops")
    check("X too many wrong PINs" in open(f"{work}/status").read(), "and tells the shell why")
finally:
    shutil.rmtree(work)

print(f"{checks} checks, {failures} failures")
sys.exit(1 if failures else 0)
