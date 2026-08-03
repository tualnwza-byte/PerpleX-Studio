"""Discovery and validation of a local Perple_X installation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REQUIRED_EXECUTABLES = (
    "build.exe",
    "convex.exe",
    "vertex.exe",
    "werami.exe",
    "psvdraw.exe",
    "pssect.exe",
)
OPTION_FILE_NAME = "perplex_option.dat"


@dataclass(frozen=True)
class PerpleXInstallation:
    """A validated Perple_X distribution available to PerpleX Studio."""

    root: Path
    bin_directory: Path
    datafiles_directory: Path
    optionfiles_directory: Path
    executables: dict[str, Path]
    option_file: Path

    @classmethod
    def discover(cls, root: str | Path) -> "PerpleXInstallation":
        """Validate *root* and return the executables needed for the first workflow.

        Perple_X is not copied or altered. Studio stores the selected installation
        path and executes programs against isolated project working directories.
        """
        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            raise ValueError(f"Perple_X installation folder does not exist: {root_path}")

        bin_directory = root_path / "bin"
        datafiles_directory = root_path / "datafiles"
        optionfiles_directory = root_path / "optionfiles"
        for directory in (bin_directory, datafiles_directory, optionfiles_directory):
            if not directory.is_dir():
                raise ValueError(f"Missing Perple_X directory: {directory}")

        executables = {name: bin_directory / name for name in REQUIRED_EXECUTABLES}
        missing = [path.name for path in executables.values() if not path.is_file()]
        if missing:
            raise ValueError("Missing required Perple_X executable(s): " + ", ".join(missing))

        option_file = optionfiles_directory / OPTION_FILE_NAME
        if not option_file.is_file():
            raise ValueError(f"Missing Perple_X option file: {option_file}")

        return cls(
            root=root_path,
            bin_directory=bin_directory,
            datafiles_directory=datafiles_directory,
            optionfiles_directory=optionfiles_directory,
            executables=executables,
            option_file=option_file,
        )
