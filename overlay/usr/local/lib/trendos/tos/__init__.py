"""TREND OS shell package (runs on the phone under /usr/local/lib/trendos).

Foundations:
  config      every tunable constant (screen, layout, colours, timings, paths, keys)
  native      the Python/C boundary: the only module allowed to import ctypes

Packages:
  hw/         the devices: framebuffer, input, Bluetooth/FM chip, audio, SSH monitor
  models/     3D model library: Shape, boxes/extrude building blocks, the launcher icons by name
  apps/       App base class, and one folder per app

Drawing:
  gfx         cached fonts, text strips, RGBX conversion, clipped copies
  canvas      fast 2D straight into RGBX arrays via libtrend
  render      ASCII tile atlas, rotations, 3D drawing via libtrend
  ui          the shared look for app screens: palette, cards, keys
  keyboard    on-screen keyboard

The shell:
  shell       the main loop (Shell)
  launcher    carousel of spinning objects (home cube + apps)
  transition  slide between screens
  flight      flies an app's icon between the carousel and its title badge
  stats       system stats sampling + the stats panel
  title       typewriter title animation
  power       power menu + full-screen messages
  boot        boot frame / loading-spin export, handover from the ramdisk, startup sound
"""
