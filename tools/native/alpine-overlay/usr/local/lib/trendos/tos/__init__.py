"""TREND OS shell package (runs on the phone under /usr/local/lib/trendos).

Modules:
  config    every tunable constant (screen, layout, colours, timings, paths, keys)
  fb        framebuffer pages, page flip + vsync, screen sleep/wake
  gfx       cached fonts, text strips, RGBX conversion, clipped copies
  render    ASCII tile atlas, rotations, C renderer (libtrend.so) + numpy fallback
  models/   3D model library: Shape, boxes/extrude building blocks, the launcher icons by name
  stats     system stats sampling + the stats panel
  title     typewriter title animation
  inputdev  touchscreen + key events
  launcher  carousel of spinning objects (home cube + apps)
  power     power menu + full-screen messages
  boot      boot frame / loading-spin export, handover from the ramdisk, startup sound
  apps/     App base class and the apps
  shell     the main loop (Shell)
"""
