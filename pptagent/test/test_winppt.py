"""Tests for the WSL -> Windows PowerPoint conversion bridge.

These tests cover the pure logic of the bridge only. Anything that actually
drives PowerPoint lives in smoketest/06_win_convert.py, because it needs a
Windows session with Office installed.
"""

import subprocess
import sys
from pathlib import Path
from shutil import which

import pytest

from pptagent.winppt import (
    bridge_status,
    build_convert_command,
    diagnose,
    find_win_python,
    interop_ready,
    is_windows_visible,
    staging_base,
    to_windows_path,
    windows_staging,
)
from pptagent.winppt import WIN_CONVERT_SCRIPT, office_mode, should_use_bridge

in_wsl = pytest.mark.skipif(
    which("wslpath") is None, reason="requires WSL (wslpath is unavailable)"
)


def test_paths_on_a_drive_mount_are_windows_visible():
    assert is_windows_visible(Path("/mnt/c/Users/foo/deck.pptx"))


def test_linux_only_paths_are_not_windows_visible():
    assert not is_windows_visible(Path("/tmp/deck.pptx"))


def test_mounts_that_are_not_drive_letters_are_not_windows_visible():
    assert not is_windows_visible(Path("/mnt/wsl/deck.pptx"))


@in_wsl
def test_to_windows_path_renders_a_drive_mount_as_a_drive_letter():
    assert to_windows_path(Path("/mnt/c/Windows")) == "C:\\Windows"


# binfmt_misc entries start with a line saying whether the handler is enabled.
ENABLED_BINFMT = "enabled\ninterpreter /init\nflags: PF\noffset 0\nmagic 4d5a\n"
DISABLED_BINFMT = ENABLED_BINFMT.replace("enabled", "disabled", 1)


def test_interop_is_ready_when_the_binfmt_handler_is_enabled(tmp_path):
    entry = tmp_path / "WSLInterop"
    entry.write_text(ENABLED_BINFMT)
    assert interop_ready(entry)


def test_interop_is_not_ready_when_the_binfmt_handler_is_disabled(tmp_path):
    entry = tmp_path / "WSLInterop"
    entry.write_text(DISABLED_BINFMT)
    assert not interop_ready(entry)


def test_interop_is_not_ready_when_the_binfmt_entry_is_missing(tmp_path):
    assert not interop_ready(tmp_path / "WSLInterop")


def test_diagnose_blames_interop_when_windows_binaries_cannot_run():
    ok, reason = diagnose(interop_ready=False, win_python=Path("/mnt/c/py/python.exe"))
    assert not ok
    assert "WSLInterop" in reason


def test_diagnose_blames_the_missing_interpreter_when_interop_works():
    ok, reason = diagnose(interop_ready=True, win_python=None)
    assert not ok
    assert "PPTAGENT_WIN_PYTHON" in reason


def test_diagnose_accepts_a_ready_bridge():
    ok, reason = diagnose(interop_ready=True, win_python=Path("/mnt/c/py/python.exe"))
    assert ok
    assert reason == ""


def test_find_win_python_accepts_an_explicit_interpreter(tmp_path):
    interpreter = tmp_path / "python.exe"
    interpreter.touch()
    assert find_win_python(str(interpreter)) == interpreter


def test_find_win_python_rejects_an_explicit_path_that_does_not_exist(tmp_path):
    assert find_win_python(str(tmp_path / "nope.exe")) is None


def test_bridge_status_is_unavailable_without_interop(tmp_path):
    entry = tmp_path / "WSLInterop"
    entry.write_text(DISABLED_BINFMT)
    ok, reason = bridge_status(binfmt=entry)
    assert not ok
    assert "WSLInterop" in reason


def test_bridge_status_is_available_with_interop_and_an_interpreter(tmp_path):
    entry = tmp_path / "WSLInterop"
    entry.write_text(ENABLED_BINFMT)
    interpreter = tmp_path / "python.exe"
    interpreter.touch()
    ok, reason = bridge_status(binfmt=entry, win_python=str(interpreter))
    assert ok
    assert reason == ""


@in_wsl
def test_staging_base_skips_directories_windows_cannot_open(tmp_path):
    # tmp_path lives on the Linux filesystem, which Windows only sees over UNC.
    assert staging_base([tmp_path, Path("/mnt/c")]) == Path("/mnt/c")


def test_staging_base_rejects_a_candidate_that_does_not_exist(tmp_path):
    with pytest.raises(RuntimeError, match="staging directory"):
        staging_base([tmp_path, Path("/mnt/c/pptagent/definitely/absent")])


@in_wsl
def test_windows_staging_yields_a_directory_windows_can_open():
    with windows_staging() as staged:
        assert is_windows_visible(staged)
        assert staged.is_dir()
    assert not staged.exists()


@in_wsl
def test_build_convert_command_converts_arguments_but_not_the_interpreter():
    cmd = build_convert_command(
        Path("/mnt/c/py/python.exe"),
        Path("/mnt/c/stage/win_convert.py"),
        "pdf",
        Path("/mnt/c/stage/in.pptx"),
        Path("/mnt/c/stage/out.pdf"),
    )
    # WSL launches the interpreter through its Linux path; everything the
    # interpreter itself opens has to be a Windows path.
    assert cmd[0] == "/mnt/c/py/python.exe"
    assert cmd[1] == "C:\stage\win_convert.py"
    assert cmd[2] == "pdf"
    assert cmd[3:] == ["C:\stage\in.pptx", "C:\stage\out.pdf"]


def test_win_convert_rejects_an_unknown_mode():
    # Runs under Linux on purpose: the Windows-only imports must stay inside
    # the mode branches, or the script cannot even report its own usage.
    result = subprocess.run(
        [sys.executable, str(WIN_CONVERT_SCRIPT), "bogus", "in.pptx", "out.pdf"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "bogus" in result.stderr + result.stdout


def test_office_mode_is_off_by_default(monkeypatch):
    monkeypatch.delenv("PPTAGENT_OFFICE_MODE", raising=False)
    assert not office_mode()


def test_office_mode_is_on_when_the_environment_asks_for_it(monkeypatch):
    monkeypatch.setenv("PPTAGENT_OFFICE_MODE", "1")
    assert office_mode()


def test_office_mode_forces_the_bridge_even_when_libreoffice_exists():
    assert should_use_bridge(has_local_converter=True, office=True, available=False)


def test_the_bridge_is_skipped_when_libreoffice_can_do_the_job():
    assert not should_use_bridge(has_local_converter=True, office=False, available=True)


def test_the_bridge_takes_over_when_libreoffice_is_absent():
    assert should_use_bridge(has_local_converter=False, office=False, available=True)


def test_no_bridge_when_it_is_neither_asked_for_nor_available():
    assert not should_use_bridge(
        has_local_converter=False, office=False, available=False
    )
