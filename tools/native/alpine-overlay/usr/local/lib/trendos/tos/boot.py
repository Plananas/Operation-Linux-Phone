"""Boot integration: the early logo frame and loading-spin frames for the ramdisk, taking over
from the ramdisk's bootanim, and the startup sound."""
import os, struct, subprocess, time

import numpy as np

from .config import (W, H, TOP, BAND, TITLE, TITLE_Y, TITLE_H, STATS_Y, STATS_H, ACCENT, GREY, DIM,
                     ROWS, COLS, CH, CW, BOOT_FPS, BOOT_N, BOOTANIM_PID, SOUND, SOUND_PLAYED)
from .gfx import canvas, centre_text, font, text_strip, to_rgbx
from .render import TILES, boot_matrix, compose, shape_grid


def boot_frame(cube):
    """Full-screen frame shown by the ramdisk right after the bootloader logo:
    title + cube at the loading spin's first pose + 'booting...' where the stats go."""
    img = np.zeros((H, W, 4), np.uint8)
    img[TITLE_Y:TITLE_Y + TITLE_H] = text_strip(TITLE, 28, ACCENT, TITLE_H)
    img[TOP:TOP + BAND] = compose(shape_grid(boot_matrix(0.0), cube))
    im, d = canvas(STATS_H)
    d.line([(16, 2), (W - 16, 2)], fill=DIM, width=1)
    centre_text(d, 80, "booting...", font(15), GREY)
    img[STATS_Y:STATS_Y + STATS_H] = to_rgbx(im)
    return img


def export_bootanim(path, cube):
    """Frames for /bin/bootanim: header + tiles + one tile-index grid per frame."""
    grids = np.stack([shape_grid(boot_matrix(k / BOOT_FPS), cube) for k in range(BOOT_N)]).astype(np.uint8)
    hdr = struct.pack("<4s8I", b"BANM", BOOT_N, ROWS, COLS, CH, CW, TOP, BOOT_FPS, len(TILES))
    with open(path, "wb") as f:
        f.write(hdr + TILES.tobytes() + grids.tobytes())


def stop_bootanim():
    """Stop the ramdisk's loading spin (if running) so only the shell draws from now on."""
    try:
        pid = int(open(BOOTANIM_PID).read())
        os.kill(pid, 15)
    except (OSError, ValueError):
        return
    for _ in range(100):
        try:
            os.kill(pid, 0); time.sleep(0.005)
        except OSError:
            break


PLAYER = "/usr/local/sbin/play-startup-sound"    # re-routes audio + retries, logs attempts


def play_startup_sound():
    """Once per boot (marker in /run), in the background."""
    if not os.path.exists(SOUND) or os.path.exists(SOUND_PLAYED):
        return
    try:
        cmd = [PLAYER] if os.access(PLAYER, os.X_OK) else ["aplay", "-q", "-D", "hw:CARD=sprdphone,DEV=0", SOUND]
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        open(SOUND_PLAYED, "w").close()
    except OSError:
        pass
