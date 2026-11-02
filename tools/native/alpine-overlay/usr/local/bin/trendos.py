#!/usr/bin/env python3
"""TREND OS shell entry point (OpenRC service "bootscreen").

  trendos.py                     run the shell
  trendos.py --boot-frame FILE   write the early-logo frame (raw 480x800 RGBX) for the ramdisk
  trendos.py --boot-anim FILE    write the loading-spin frames for the ramdisk's bootanim
"""
import sys

sys.path.insert(0, "/usr/local/lib/trendos")


def main(argv):
    if len(argv) == 3 and argv[1] in ("--boot-frame", "--boot-anim"):
        from tos import boot, models
        from tos.render import Renderer
        renderer, cube = Renderer(), models.get("cube")
        if argv[1] == "--boot-frame":
            with open(argv[2], "wb") as f:
                f.write(boot.boot_frame(renderer, cube).tobytes())
        else:
            boot.export_bootanim(argv[2], renderer, cube)
        return
    from tos.shell import Shell
    Shell().run()


if __name__ == "__main__":
    main(sys.argv)
