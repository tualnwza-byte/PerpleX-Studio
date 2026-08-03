"""Safe subprocess execution for Perple_X calculations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import copy2, which
from subprocess import CompletedProcess, run

from perplex_studio.perplex_installation import PerpleXInstallation


@dataclass(frozen=True)
class StagedProject:
    """A BUILD output and its declared dependencies in an isolated directory."""

    project_name: str
    working_directory: Path
    project_file: Path
    copied_dependencies: tuple[Path, ...]


def calculation_type(project_file: str | Path) -> int:
    """Return the Perple_X calculation type recorded in a BUILD definition."""
    path = Path(project_file)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 7:
        raise ValueError(f"Project file is incomplete: {path}")
    try:
        return int(lines[6].split()[0])
    except (IndexError, ValueError) as error:
        raise ValueError(f"Cannot read calculation type from: {path}") from error


def find_ghostscript() -> Path | None:
    """Locate a user-installed 64-bit Ghostscript command-line executable."""
    command = which("gswin64c.exe") or which("gswin64c")
    if command:
        return Path(command)
    candidates = sorted(Path("C:/Program Files/gs").glob("gs*/bin/gswin64c.exe"), reverse=True)
    return candidates[0] if candidates else None


def _declared_file_name(line: str) -> str:
    """Read the filename token from a BUILD definition line.

    Perple_X writes explanatory text after some filenames without requiring a
    comment marker, e.g. ``hp02ver.dat thermodynamic data file``.
    """
    value = line.strip()
    if not value or value.startswith("|"):
        return ""
    return value.split(maxsplit=1)[0]


def stage_project(
    project_file: str | Path,
    working_directory: str | Path,
    installation: PerpleXInstallation,
) -> StagedProject:
    """Copy a BUILD output and its declared dependencies for a calculation run.

    The source project and installation are read only. Existing files in the
    target working directory are rejected to prevent accidental overwrites.
    """
    source = Path(project_file).expanduser().resolve()
    target = Path(working_directory).expanduser().resolve()
    if source.suffix.lower() != ".dat" or not source.is_file():
        raise ValueError(f"Expected an existing Perple_X project .dat file: {source}")
    if target.exists():
        raise ValueError(f"Run directory already exists: {target}")

    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 6:
        raise ValueError(f"Project file is incomplete (expected at least 6 lines): {source}")

    project_name = source.stem
    target.mkdir(parents=True)
    target_project = target / source.name
    copy2(source, target_project)

    dependencies: list[Path] = []
    # BUILD writes database, print, plot, solution model, project name, options.
    for dependency_name, fallback_directory in (
        (_declared_file_name(lines[0]), installation.datafiles_directory),
        (_declared_file_name(lines[3]), installation.datafiles_directory),
        (_declared_file_name(lines[5]), installation.optionfiles_directory),
    ):
        if not dependency_name:
            continue
        source_dependency = source.parent / dependency_name
        if not source_dependency.is_file():
            source_dependency = fallback_directory / dependency_name
        if not source_dependency.is_file():
            raise ValueError(f"Project dependency was not found: {dependency_name}")
        destination = target / dependency_name
        copy2(source_dependency, destination)
        dependencies.append(destination)

    plot_options = "perplex_plot_option.dat"
    source_plot_options = source.parent / plot_options
    if not source_plot_options.is_file():
        source_plot_options = installation.optionfiles_directory / plot_options
    if source_plot_options.is_file():
        destination = target / plot_options
        copy2(source_plot_options, destination)
        dependencies.append(destination)

    return StagedProject(
        project_name=project_name,
        working_directory=target,
        project_file=target_project,
        copied_dependencies=tuple(dependencies),
    )


def run_convex(
    staged_project: StagedProject,
    installation: PerpleXInstallation,
    *,
    timeout_seconds: float | None = None,
) -> CompletedProcess[str]:
    """Run CONVEX for a staged project and capture its full console output."""
    return run(
        [str(installation.executables["convex.exe"])],
        cwd=staged_project.working_directory,
        input=f"{staged_project.project_name}\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )


def run_vertex(
    staged_project: StagedProject,
    installation: PerpleXInstallation,
    *,
    timeout_seconds: float | None = None,
) -> CompletedProcess[str]:
    """Run VERTEX for a staged constrained-minimization project."""
    return run(
        [str(installation.executables["vertex.exe"])],
        cwd=staged_project.working_directory,
        input=f"{staged_project.project_name}\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )


def run_pssect(
    staged_project: StagedProject,
    installation: PerpleXInstallation,
    *,
    timeout_seconds: float | None = None,
) -> CompletedProcess[str]:
    """Render a VERTEX grid result to PostScript with default PSSECT options."""
    return run(
        [str(installation.executables["pssect.exe"])],
        cwd=staged_project.working_directory,
        input=f"{staged_project.project_name}\nn\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )


def run_psvdraw(
    staged_project: StagedProject,
    installation: PerpleXInstallation,
    *,
    timeout_seconds: float | None = None,
) -> CompletedProcess[str]:
    """Render a compatible Perple_X plot file to PostScript using PSVDRAW."""
    return run(
        [str(installation.executables["psvdraw.exe"])],
        cwd=staged_project.working_directory,
        input=f"{staged_project.project_name}\nn\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
