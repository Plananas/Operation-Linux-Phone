"""ASCII preview of models, as the launcher draws them (needs numpy, so run it on the phone):

    python3 -m tos.models                  list the models
    python3 -m tos.models spotify plus     front view + a swayed view of each
    python3 -m tos.models spotify --pose 0.3,0.8,0.1    a specific (nod, yaw, roll) in radians
"""
import sys

from ..config import APP_SWAY, APP_TILT, K_APP, NS, SHADES
from ..render import matrix, shape_grid
from . import get, names


def show(name, pose):
    shape = get(name)
    print(f"== {name}  pose={pose}  ({len(shape.pts)} points, {len(shape.fnrm)} faces)")
    for row in shape_grid(matrix(APP_TILT, *pose), shape, K_APP):
        if row.any():
            print("".join(SHADES[v % NS] if v else " " for v in row).rstrip())


def main(argv):
    if not argv:
        print("models:", " ".join(names()))
        return
    poses = [(0.0, 0.0, 0.0), tuple(0.8 * amp for amp, _ in APP_SWAY)]
    if "--pose" in argv:
        i = argv.index("--pose")
        poses = [tuple(float(v) for v in argv[i + 1].split(","))]
        argv = argv[:i] + argv[i + 2:]
    for name in argv:
        if name not in names():
            sys.exit(f"unknown model {name!r}; have: {' '.join(names())}")
        for pose in poses:
            show(name, pose)


main(sys.argv[1:])
