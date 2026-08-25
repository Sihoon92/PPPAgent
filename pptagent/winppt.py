"""Bridge that drives Windows PowerPoint from inside WSL.

Office machines often cannot install LibreOffice, which leaves `soffice` and
`unoconvert` unavailable. Windows itself has PowerPoint, so this module hands
files to a Python interpreter on the Windows side, which talks to PowerPoint
over COM (pywin32).
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from shutil import which

# WSL exposes Windows drives through drvfs at /mnt/<letter>. Only paths under
# such a mount have a plain Windows path; anything else is reachable solely
# through the \\wsl.localhost UNC share, which PowerPoint handles poorly.
_DRIVE_MOUNT = re.compile(r"^/mnt/[a-z](/|$)", re.IGNORECASE)

# Kernel-side registration that lets WSL run .exe files.
WSL_INTEROP_BINFMT = Path("/proc/sys/fs/binfmt_misc/WSLInterop")

NO_INTEROP = (
    "WSL cannot execute Windows binaries: the WSLInterop binfmt handler is not "
    "registered. Distros booting with systemd=true often lose it to "
    "systemd-binfmt; re-register it or disable systemd."
)
# PowerPoint opens files through the Windows filesystem, so anything handed to
# it has to sit on a drive mount. C:\Users\Public exists and is writable on
# every Windows install, which makes it a dependable staging area.
DEFAULT_STAGING_BASES = (Path("/mnt/c/Users/Public"), Path("/mnt/c/Windows/Temp"))

NO_WIN_PYTHON = (
    "no Windows Python interpreter found. Install Python on the Windows side "
    "along with pywin32, then point PPTAGENT_WIN_PYTHON at it."
)


def is_windows_visible(path: Path) -> bool:
    """True if Windows can open this path directly, without a UNC share."""
    return _DRIVE_MOUNT.match(path.as_posix()) is not None


def to_windows_path(path: Path) -> str:
    """Render a WSL path the way Windows sees it."""
    result = subprocess.run(
        ["wslpath", "-w", str(path)], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def interop_ready(binfmt: Path = WSL_INTEROP_BINFMT) -> bool:
    """True if the kernel is currently willing to execute Windows binaries."""
    if not binfmt.exists():
        return False
    return binfmt.read_text().splitlines()[0].strip() == "enabled"


def diagnose(interop_ready: bool, win_python: Path | None) -> tuple[bool, str]:
    """Decide whether the bridge can run, and say why when it cannot."""
    if not interop_ready:
        return False, NO_INTEROP
    if win_python is None:
        return False, NO_WIN_PYTHON
    return True, ""


def find_win_python(explicit: str | None = None) -> Path | None:
    """Locate the Windows interpreter that will run the conversion script."""
    if explicit:
        candidate = Path(explicit)
        return candidate if candidate.exists() else None
    found = which("python.exe")
    return Path(found) if found is not None else None


def bridge_status(
    binfmt: Path = WSL_INTEROP_BINFMT, win_python: str | None = None
) -> tuple[bool, str]:
    """Probe this machine and report whether the bridge can run."""
    explicit = win_python or os.environ.get("PPTAGENT_WIN_PYTHON")
    return diagnose(interop_ready(binfmt), find_win_python(explicit))


def staging_base(candidates: Sequence[Path] = DEFAULT_STAGING_BASES) -> Path:
    """Pick a directory that both Windows and this process can write to."""
    for candidate in candidates:
        if (
            is_windows_visible(candidate)
            and candidate.is_dir()
            and os.access(candidate, os.W_OK)
        ):
            return candidate
    raise RuntimeError(
        "no usable staging directory: PowerPoint can only open files on a "
        f"Windows drive mount, and none of {[str(c) for c in candidates]} "
        "is a writable one. Set PPTAGENT_WIN_TEMP to a directory under /mnt."
    )


@contextmanager
def windows_staging() -> Iterator[Path]:
    """A scratch directory that Windows can open by plain path."""
    configured = os.environ.get("PPTAGENT_WIN_TEMP")
    bases = (Path(configured),) if configured else DEFAULT_STAGING_BASES
    staged = Path(tempfile.mkdtemp(prefix="pptagent-", dir=staging_base(bases)))
    try:
        yield staged
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def office_mode() -> bool:
    """True when the operator has pinned this machine to the Windows bridge."""
    return os.environ.get("PPTAGENT_OFFICE_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def should_use_bridge(has_local_converter: bool, office: bool, available: bool) -> bool:
    """Office mode always wins; otherwise the bridge only fills a gap."""
    if office:
        return True
    return not has_local_converter and available


# Shipped with the package and copied into the staging directory per run, so
# the Windows interpreter never has to reach into the Linux filesystem.
WIN_CONVERT_SCRIPT = Path(__file__).parent / "scripts" / "win_convert.py"


def build_convert_command(
    win_python: Path, script: Path, mode: str, src: Path, dst: Path
) -> list[str]:
    """Build the argv that runs the Windows-side converter."""
    return [
        str(win_python),
        to_windows_path(script),
        mode,
        to_windows_path(src),
        to_windows_path(dst),
    ]


def _resolve_interpreter() -> Path:
    """The Windows interpreter to drive, or an explanation of why there isn't one."""
    win_python = find_win_python(os.environ.get("PPTAGENT_WIN_PYTHON"))
    ok, reason = diagnose(interop_ready(), win_python)
    if not ok:
        raise RuntimeError(f"Windows PowerPoint bridge unavailable: {reason}")
    assert win_python is not None
    return win_python


def convert(mode: str, src: Path, dst: Path) -> None:
    """Convert one file by handing it to Windows.

    Both the input and the converter script are staged on a drive mount first,
    because PowerPoint cannot reliably open files over the \\wsl.localhost share.
    """
    win_python = _resolve_interpreter()
    with windows_staging() as staged:
        script = staged / WIN_CONVERT_SCRIPT.name
        shutil.copy(WIN_CONVERT_SCRIPT, script)
        staged_src = staged / src.name
        shutil.copy(src, staged_src)
        staged_dst = staged / dst.name

        command = build_convert_command(
            win_python, script, mode, staged_src, staged_dst
        )
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Windows converter failed ({mode}): "
                f"{(result.stderr or result.stdout).strip()}"
            )
        if not staged_dst.exists():
            raise RuntimeError(
                f"Windows converter reported success but produced no {mode} output"
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(staged_dst, dst)


async def pptx_to_pdf(src: Path, dst: Path) -> None:
    """Export a presentation to PDF through PowerPoint."""
    await asyncio.to_thread(convert, "pdf", src, dst)


def wmf_to_png(src: Path, dst: Path) -> None:
    """Rasterise a WMF/EMF image through the Windows imaging stack."""
    convert("wmf", src, dst)
