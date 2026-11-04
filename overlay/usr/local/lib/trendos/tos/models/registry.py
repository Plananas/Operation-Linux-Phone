"""Name -> model lookup. Models are built on first use and cached (building takes a moment)."""

_BUILDERS = {}                  # name -> (builder function, palette index)
_CACHE = {}


def model(name, colour):
    """Decorator registering a shape builder under `name`; `colour` (palette index) is the
    icon's accent colour, used for its launcher label."""
    def register(fn):
        if name in _BUILDERS:
            raise ValueError(f"model {name!r} registered twice")
        _BUILDERS[name] = (fn, colour)
        return fn
    return register


def get(name):
    """The Shape for `name` (built once)."""
    if name not in _CACHE:
        _CACHE[name] = _BUILDERS[name][0]()
    return _CACHE[name]


def colour(name):
    return _BUILDERS[name][1]


def names():
    return list(_BUILDERS)
