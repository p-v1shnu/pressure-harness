# PyInstaller spec for a single-file `ph` executable.
#
# One file because the alternative is asking someone to keep a folder intact,
# and a console that stops working when a stray DLL is moved is a console
# nobody trusts. The startup cost of unpacking is paid once per command; `ph`
# is not something anyone runs in a loop.
#
# The console page is a Python string rather than an HTML file on disk, so
# there is nothing to bundle as data -- which is also why it cannot go missing.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# These are imported by name at runtime, so static analysis does not see them.
hidden = [
    *collect_submodules("uvicorn"),
    *collect_submodules("websockets"),
    "pharness.adapters.windows.paths",
    "pharness.adapters.windows.process",
    "pharness.adapters.windows.shell",
    "pharness.adapters.posix.paths",
    "pharness.adapters.posix.process",
    "pharness.adapters.posix.shell",
    "pharness.adapters.macos.paths",
    "pharness.adapters.macos.shell",
]

# `mcp.cli` exits the interpreter at import time when its optional CLI extras
# are missing, which kills the build instead of being skipped. Nothing here uses
# it, so it is left out entirely.
def wanted(module: str) -> bool:
    return not module.startswith("mcp.cli")


hidden += collect_submodules("mcp", filter=wanted)

datas = []
binaries = []
for package in ("mcp", "pydantic", "starlette"):
    try:
        package_datas, package_binaries, _ = collect_all(package, filter_submodules=wanted)
    except TypeError:  # an older PyInstaller without the filter argument
        package_datas, package_binaries, _ = collect_all(package)
    datas += package_datas
    binaries += package_binaries

analysis = Analysis(
    ["entry.py"],
    pathex=[str(Path(SPECPATH).parent / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    excludes=["mcp.cli", "tkinter.test", "test", "unittest", "pytest", "hypothesis"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="ph",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
