"""Source-checkout shim so ``python -m math_agent...`` uses this repository.

The distributable package remains the canonical implementation under ``src/``;
setuptools is configured to package only that tree.
"""

from pathlib import Path

_SOURCE_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "math_agent"
if not _SOURCE_PACKAGE.is_dir():
    raise ImportError("local math_agent source package is missing")

__path__ = [str(_SOURCE_PACKAGE)]
__all__ = ["__version__"]
__version__ = "0.1.0"
