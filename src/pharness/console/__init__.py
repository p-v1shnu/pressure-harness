"""The console: where the owner sees, approves, and takes back.

Served locally rather than rendered natively, so the same page works in a
window, in a browser, and in a test.
"""

from pharness.console.api import ConsoleApi
from pharness.console.app import build_console_app, new_token

__all__ = ["ConsoleApi", "build_console_app", "new_token"]
