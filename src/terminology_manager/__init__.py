"""Terminology Manager package."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("terminology-manager")
except PackageNotFoundError:
    # Fallback für PyInstaller-Builds ohne gebündelte Paketmetadaten.
    __version__ = "1.2"
