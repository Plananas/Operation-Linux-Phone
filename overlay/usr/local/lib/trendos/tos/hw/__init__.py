"""Talking to the phone's devices. Nothing here draws, and nothing imports above tos.config.

  fb        framebuffer pages, page flip + vsync, screen sleep/wake
  inputdev  touchscreen + key events
  btchip    the BCM43430A1 Bluetooth/FM chip: power, patch, UART speed, vendor HCI
  fm        FM radio driver (on top of btchip)
  bluetooth long-lived bluetoothctl as pairing agent + parsed device list
  audio     Bluetooth audio sink lookup
  sshmon    who is connected over SSH (/proc/net/tcp, sshd processes, the log)
"""
