"""TREND OS configuration: every tunable constant lives here."""
import math, os

# ---- hardware ----------------------------------------------------------------------
W, H = 480, 800                    # sprdfb panel, 32 bpp, byte order R,G,B,X
FB_DEV = "/dev/fb0"
NPAGES = 3                         # triple buffering (virtual size is 480 x 2400)
TOUCH_DEV = "/dev/input/event1"    # ist30xx, MT protocol B; also carries KEY_BACK
KEYS_DEV = "/dev/input/event0"     # sci-keypad: Home, Power, Volume
KEY_HOME, KEY_BACK, KEY_POWER = 102, 158, 116
BACKLIGHT = "/sys/class/backlight/panel/brightness"
BRIGHTNESS = 160                   # never write 0: the driver then disables the backlight

# ---- paths ---------------------------------------------------------------------------
LIBTREND = os.environ.get("TREND_LIBTREND", "/usr/local/lib/trendos/libtrend.so")
LIBTRENDPLAY = "/usr/local/lib/trendos/libtrendplay.so"
MUSIC_DIR = "/data/music"
SOUND = "/usr/local/share/trendos/startup.wav"
SOUND_PLAYED = "/run/trendos-sound-played"         # play once per boot, not on respawn
BOOTANIM_PID = "/dev/.bootanim.pid"                 # written by the ramdisk's bootanim
# UI text: VT323, a revival of the DEC VT320 terminal font (one weight, SIL OFL), to match the
# green-phosphor terminal look. Sizes in the code are DejaVu-equivalent px; gfx.font() scales.
FONT_UI = "/usr/local/share/trendos/fonts/VT323-Regular.ttf"
FONT_UI_SCALE = 1.3                # VT323 cap height is 0.56 em vs DejaVu's 0.73 em
# The ASCII-shaded 3D objects keep DejaVu Sans Mono: SHADES' density ramp is tuned to it.
FONT_ART = "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf"

# ---- look ----------------------------------------------------------------------------
TITLE = "TREND OS"
GREET_NAME = "Robin"
ACCENT, GREY, DIM, TEXT = (0, 255, 140), (130, 130, 130), (60, 60, 60), (220, 220, 220)
PALETTE = [(255, 70, 70), (70, 255, 110), (80, 140, 255), (255, 215, 50),
           (255, 80, 255), (50, 230, 230), (255, 150, 40), (230, 230, 230), (30, 215, 96),
           (30, 110, 62)]
RED, GREEN, BLUE, YELLOW, MAGENTA, CYAN, ORANGE, WHITE, SPOTIFY, DIMGREEN = range(10)   # PALETTE indices
SHADES = " .,-~:;=!*#$@"          # ASCII shading, index 0 = empty cell
NS = len(SHADES)

# ---- layout --------------------------------------------------------------------------
FONT_PX, CW, CH = 12, 8, 12        # character cell: 60 x 44 cells, rows exactly screen-wide
COLS, ROWS = W // CW, 44
TITLE_Y, TITLE_H = 22, 36
TOP = 66                           # object band: TOP .. TOP + BAND
BAND = ROWS * CH
LABEL_Y = BAND - 50                # app label (inside the band, below the object)
DOTS_Y = BAND - 16                 # page dots
STATS_Y, STATS_H = 600, 196        # stats panel
APP_H = H - TOP                    # app screens use TOP .. H

# ---- 3D --------------------------------------------------------------------------------
LIGHT = (-2.5, 3.0, -5.0)          # point light
CAM_Z = -4.5                       # camera at (0, 0, CAM_Z)
ASPECT = CW / CH
K_BOOT = COLS * 1.03               # projection scale of the boot animation
K_APP = COLS * 0.93                # launcher size (leaves room for label + dots)
FULL_RATES = (0.9, 0.62, 0.35)     # rad/s about x, y, z in the full tumble (home cube)
# App icons sway instead of tumbling, so they stay upright and recognisable: each axis
# oscillates (amplitude rad, rate rad/s) about a front-facing pose, seen from slightly above.
APP_SWAY = ((0.36, 1.1), (0.95, 0.8), (0.14, 0.45))    # (amp, rate) for x (nod), y (yaw), z (roll)
APP_TILT = 0.30

# Boot "loading" spin (played by /bin/bootanim until the shell takes over): spin about the
# vertical axis, view tilted. Frame k is shown at CLOCK_MONOTONIC t with
# k = floor(t * BOOT_FPS) % BOOT_N, so the angle is always BOOT_W * t and the shell can
# continue from exactly the same pose.
BOOT_TILT = 0.45
BOOT_PERIOD = 4.0
BOOT_FPS = 30
BOOT_N = int(BOOT_PERIOD * BOOT_FPS)
BOOT_W = 2 * math.pi / BOOT_PERIOD
BLEND = 2.5                        # s to ease from the loading spin into the full tumble

# ---- behaviour ---------------------------------------------------------------------------
MAX_FPS = 30
SLEEP_AFTER = 120                  # s without input -> screen off
LONG_PRESS = 0.9                   # s holding Power -> power menu
SWIPE_FRACTION = 0.25              # drag past this fraction of the width -> next app
SWIPE_FLICK = 700                  # px/s flick velocity -> next app
TAP_TIME, DRAG_START = 0.5, 12     # s / px
