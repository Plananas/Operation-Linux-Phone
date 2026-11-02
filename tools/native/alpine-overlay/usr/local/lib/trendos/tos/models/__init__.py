"""3D model library: the launcher icons and the building blocks for new ones.

To add an icon:
  1. In tos/models/icons.py, write a function returning a Shape (usually via boxes() or
     extrude() from tos/models/shape.py) and decorate it with @model("name", COLOUR).
  2. Preview it as ASCII on the phone:
       cd /usr/local/lib/trendos && python3 -m tos.models name
  3. Use it in tos/launcher.py: Entry("name", SomeApp(), ...).
"""
from . import icons             # noqa: F401  (registers the built-in models)
from .registry import colour, get, model, names
from .shape import Shape, arc, boxes, extrude

__all__ = ["Shape", "arc", "boxes", "colour", "extrude", "get", "model", "names"]
