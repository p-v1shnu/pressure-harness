# Locked dependencies

Every version here is pinned to an exact release and to the hash of the file
that release consists of. A pinned version alone says which release was asked
for; the hash says which bytes arrived, which is the part an attacker would
change (OWASP A03:2025, LLM03).

Regenerate after editing `pyproject.toml`:

    pip install uv
    ./requirements/lock.sh

The resolution is **universal**, so one lock covers every platform with the
markers that select each dependency. A resolver run on Linux produces a Linux
lock, and `--require-hashes` then refuses to install what it left out: that is
how every Windows CI run died at `import colorama` for a day.

CI installs from these with `--require-hashes`, so an unexpected file fails the
build instead of running.
