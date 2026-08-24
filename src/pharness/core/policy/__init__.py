"""The layer that sits between transport and tools.

No tool is reachable except through `engine.decide` (PRD 6.1). Everything in
this package is pure: it takes a request and returns a verdict, so it can be
fuzzed exhaustively without touching a filesystem or spawning anything.
"""

from pharness.core.policy.tiers import Tier

__all__ = ["Tier"]
