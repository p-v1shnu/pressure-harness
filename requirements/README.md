# Locked dependencies

Every version here is pinned to an exact release and to the hash of the file
that release consists of. A pinned version alone says which release was asked
for; the hash says which bytes arrived, which is the part an attacker would
change (OWASP A03:2025, LLM03).

Regenerate after editing `pyproject.toml`:

    pip install pip-tools
    ./requirements/lock.sh

CI installs from these with `--require-hashes`, so an unexpected file fails the
build instead of running.
