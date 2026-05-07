"""Version discovery for copane.

Reads the version from ``pyproject.toml`` (single source of truth).
``importlib.metadata`` is preferred when the package is installed;
the TOML fallback supports ``pip install -e .`` / ``PYTHONPATH``
development setups.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def get_version() -> str:
    """Return the copane version string (e.g. ``"1.0.0"``)."""
    # Preferred: read from installed package metadata
    try:
        from importlib.metadata import version

        return version("copane")
    except Exception:
        pass

    # Fallback: parse pyproject.toml relative to this file
    # _version.py lives in python/src/copane/ — walk up to python/
    pyproject = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return str(data.get("project", {}).get("version", "0.0.0"))

    return "0.0.0"
