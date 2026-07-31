from pathlib import Path

import pytest

from perplex_studio.perplex_installation import PerpleXInstallation
from perplex_studio.runner import stage_project


def make_installation(root: Path) -> PerpleXInstallation:
    for directory in ("bin", "datafiles", "optionfiles"):
        (root / directory).mkdir(parents=True)
    for executable in ("build.exe", "vertex.exe", "werami.exe", "convex.exe", "psvdraw.exe", "pssect.exe"):
        (root / "bin" / executable).touch()
    (root / "optionfiles" / "perplex_option.dat").write_text("default options\n")
    (root / "optionfiles" / "perplex_plot_option.dat").write_text("default plot options\n")
    return PerpleXInstallation.discover(root)


def write_project(path: Path) -> None:
    path.write_text(
        "database.dat thermodynamic data file\nno_print\nplot\n"
        " | solution model file, blank = none\ndemo\n"
        "perplex_option.dat Perple_X option file\n",
        encoding="utf-8",
    )
    (path.parent / "database.dat").write_text("database", encoding="utf-8")


def test_stage_project_copies_input_and_dependencies(tmp_path: Path) -> None:
    installation = make_installation(tmp_path / "perplex")
    source = tmp_path / "input" / "demo.dat"
    source.parent.mkdir()
    write_project(source)

    staged = stage_project(source, tmp_path / "runs" / "demo-001", installation)

    assert staged.project_name == "demo"
    assert staged.project_file.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert {file.name for file in staged.copied_dependencies} == {
        "database.dat",
        "perplex_option.dat",
        "perplex_plot_option.dat",
    }


def test_stage_project_refuses_an_existing_run_directory(tmp_path: Path) -> None:
    installation = make_installation(tmp_path / "perplex")
    source = tmp_path / "demo.dat"
    write_project(source)
    run_directory = tmp_path / "runs" / "demo-001"
    run_directory.mkdir(parents=True)

    with pytest.raises(ValueError, match="already exists"):
        stage_project(source, run_directory, installation)
