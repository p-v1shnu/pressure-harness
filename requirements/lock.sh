#!/usr/bin/env bash
# Regenerate the lock files from pyproject.toml.
#
# --generate-hashes is the point: without it a lock pins a version number, and a
# version number is a label someone else controls.
set -euo pipefail
cd "$(dirname "$0")/.."

compile() {
    # --allow-unsafe pins setuptools too. The name is misleading: leaving it
    # unpinned is what is unsafe, because pip then resolves it freshly at
    # install time, unhashed, in a file whose whole purpose is that nothing is.
    pip-compile --quiet --generate-hashes --strip-extras --allow-unsafe \
        --output-file "requirements/$1.lock" "${@:2}"
}

compile runtime pyproject.toml
compile dev --extra dev pyproject.toml
compile packaging requirements/packaging.in
compile tooling requirements/tooling.in

echo "locks regenerated; commit them with the change that caused them"
