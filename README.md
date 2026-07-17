# PerpleX Studio

PerpleX Studio is a desktop application that makes the Perple_X equilibrium-modelling workflow easier to set up, run, inspect, and reproduce. It will orchestrate the existing Perple_X executables; it will not reimplement their thermodynamic calculations.

## Current status

The project is at its foundation stage. The first usable milestone is deliberately small: select a Perple_X installation and a BUILD input file, run BUILD, and view its live output.

## Planned workflow

```text
Project settings -> BUILD -> CONVEX or VERTEX -> WERAMI -> results and figures
```

See [the development roadmap](docs/roadmap.md) and [the Perple_X workflow notes](docs/perplex_workflow.md).

## Development setup

Requires Python 3.12 or newer.

For automatic figure previews, install 64-bit Ghostscript separately. Studio detects its `gswin64c.exe` executable; Ghostscript is not bundled or redistributed by this project.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Project layout

```text
src/perplex_studio/  Application package
docs/                Product and technical documentation
tests/               Automated tests
examples/            Non-proprietary example projects
assets/              Application artwork and static assets
```

## Contributing Perple_X examples

Please do not commit Perple_X databases, executables, or unpublished sample data unless their licences explicitly allow redistribution. Development needs a few successful, anonymised project folders and one failing example with its console output. See [file formats and sample data](docs/file_formats.md).
