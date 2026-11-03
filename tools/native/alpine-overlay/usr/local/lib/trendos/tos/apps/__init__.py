"""TREND OS apps. An app draws the area below the title (TOP .. H) and gets touch events there.

To add an app: subclass App, then add a launcher Entry for it in tos/launcher.py.

Shelved: spotify.py (SpotifyApp) is kept but not imported, because Spotify refuses audio keys
to librespot clients (see PLAN.md). To revive: import it here, re-add its launcher Entry,
deploy with SPOTIFY=1.
"""
from .base import App
from .calculator import CalculatorApp
from .wifi import WifiApp
from .radio import RadioApp
from .clock import ClockApp

__all__ = ["App", "CalculatorApp", "WifiApp", "RadioApp", "ClockApp"]
