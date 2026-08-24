"""Per-platform implementations of the ports.

Kept as pure logic wherever possible so every adapter can be tested from any
platform's CI. Only calls that genuinely need the host OS -- resolving a real
path, spawning a real process -- are allowed to be untestable elsewhere.
"""

from pharness.adapters.registry import Adapters, UnsupportedPlatformError, select

__all__ = ["Adapters", "UnsupportedPlatformError", "select"]
