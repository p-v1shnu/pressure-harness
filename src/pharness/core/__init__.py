"""Everything that must behave identically on every platform.

Nothing in here may import a platform module or an adapter; that boundary is
enforced by import-linter in CI rather than by remembering to keep it.
"""
