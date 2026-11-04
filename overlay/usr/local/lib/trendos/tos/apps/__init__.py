"""TREND OS apps. An app draws the area below the title (TOP .. H) and gets touch events there.

Each app has its own folder: its class is in <app>/app.py and is exported by <app>/__init__.py.
To add an app: make its folder, subclass App, then add a launcher Entry for it in tos/launcher.py.

Shelved: spotify/ (SpotifyApp) is kept but not imported, because Spotify refuses audio keys
to librespot clients (see PLAN.md). To revive: import it here, re-add its launcher Entry,
deploy with SPOTIFY=1.
"""
from .base import App
from .calculator import CalculatorApp
from .wifi import WifiApp
from .radio import RadioApp
from .music import MusicApp
from .clock import ClockApp
from .bluetooth import BluetoothApp
from .ssh import SshApp
from .files import FilesApp

__all__ = ["App", "CalculatorApp", "WifiApp", "RadioApp", "MusicApp", "ClockApp", "BluetoothApp", "SshApp", "FilesApp"]
