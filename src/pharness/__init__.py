"""Pressure Harness — a local coding agent harness for ChatGPT.

Layout mirrors the boundary the whole design rests on (PRD 14.1):

* `core/`     — knows nothing about any operating system
* `ports/`    — the contracts `core` talks through
* `adapters/` — one implementation per platform
"""

__version__ = "0.1.0.dev0"
