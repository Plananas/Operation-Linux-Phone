"""TREND OS apps. An app draws the area below the title (TOP .. H) and gets touch events there.

To add an app: subclass App, then add a launcher Entry for it in tos/launcher.py.
"""
from .base import App
from .calculator import CalculatorApp
from .wifi import WifiApp

__all__ = ["App", "CalculatorApp", "WifiApp"]
