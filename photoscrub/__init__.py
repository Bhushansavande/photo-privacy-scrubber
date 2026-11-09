"""Photo Privacy Scrubber: remove location, camera serial numbers and other hidden data from photos."""

__version__ = "0.1.0"

from .core import UnsupportedImage, clean, detect, inspect  # noqa: E402,F401
