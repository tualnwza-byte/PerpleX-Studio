from pathlib import Path

import pytest

from perplex_studio.perplex_installation import PerpleXInstallation


def make_installation(root: Path) -> None:
    for directory in ("bin", "datafiles", "optionfiles"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for executable in ("build.exe", "vertex.exe", "werami.exe", "convex.exe", "psvdraw.exe"):
        (root / "bin" / executable).touch()
    (root / "optionfiles" / "perplex_option.dat").touch()


def test_discover_accepts_a_complete_perplex_installation(tmp_path: Path) -> None:
    make_installation(tmp_path)

    installation = PerpleXInstallation.discover(tmp_path)

    assert installation.root == tmp_path.resolve()
    assert installation.executables["build.exe"] == tmp_path / "bin" / "build.exe"


def test_discover_explains_missing_required_executable(tmp_path: Path) -> None:
    make_installation(tmp_path)
    (tmp_path / "bin" / "werami.exe").unlink()

    with pytest.raises(ValueError, match="werami.exe"):
        PerpleXInstallation.discover(tmp_path)
