#!/usr/bin/env bash
# Regenerate the lock files from pyproject.toml.
#
# Two things matter here and both were learned the hard way.
#
# --generate-hashes: without it a lock pins a version number, and a version
# number is a label someone else controls.
#
# --universal: a resolver run on Linux produces a Linux lock. pytest needs
# colorama on Windows and nothing else does, so a Linux-resolved lock simply
# omits it -- and --require-hashes then refuses to install it, so pytest dies at
# import on every Windows runner. A universal resolution keeps every platform's
# dependencies with the markers that select them.
set -euo pipefail
cd "$(dirname "$0")/.."

compile() {
    uv pip compile --quiet --universal --generate-hashes --no-strip-markers \
        --python-version 3.11 \
        --output-file "requirements/$1.lock" "${@:2}"
}

compile runtime pyproject.toml
compile dev --extra dev pyproject.toml
compile packaging requirements/packaging.in
compile tooling requirements/tooling.in

echo "locks regenerated; commit them with the change that caused them"
