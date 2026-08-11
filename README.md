# PerpleX Studio

> **Experimental software - not yet validated for research use.**
> PerpleX Studio is an early-stage graphical interface for Perple_X. Always
> verify generated input files, console output, databases, solution models, and
> scientific interpretations independently before using any result in research,
> teaching, or publication.

![Status: experimental](https://img.shields.io/badge/status-experimental-7c3aed)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-2563eb)
![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776ab)
![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)

PerpleX Studio makes the Perple_X equilibrium-modelling workflow easier to set
up, run, inspect, and reproduce. It orchestrates the existing Perple_X
executables; it does **not** reimplement or distribute the Perple_X
thermodynamic engine, databases, or solution-model files.

## Required downloads

Install these separately before running Studio:

| Software | Why it is needed | Official download |
| --- | --- | --- |
| Perple_X | Thermodynamic calculation engine, databases, and solution models | [Perple_X official website](https://www.perplex.ethz.ch/) |
| Python 3.12+ (64-bit) | Runs PerpleX Studio | [Python for Windows](https://www.python.org/downloads/windows/) |
| Ghostscript (64-bit) | Converts Perple_X PostScript figures into the PNG preview | [Ghostscript downloads](https://www.ghostscript.com/releases/gsdnld.html) |

Download Studio itself from the [PerpleX Studio repository](https://github.com/tualnwza-byte/PerpleX-Studio).

## AI-assisted development

This experimental user interface was developed with assistance from AI coding
tools. Studio does **not** use AI to run Perple_X calculations, choose
scientific assumptions, validate results, or interpret pseudosections.
Perple_X remains the thermodynamic engine, and users remain responsible for
checking every input and scientific conclusion.

## Quick start

1. Install Python 3.12+, Perple_X for Windows, and 64-bit Ghostscript.
2. Download this repository, then run:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -e .
   perplex-studio
   ```

3. In Studio, select the Perple_X installation root, create a `.dat` project,
   and run the supported calculation route.

For complete instructions, including troubleshooting, see the
[Windows installation guide](docs/installation.md).

## Current capabilities

| Area | Current support |
| --- | --- |
| BUILD input | Guided project name, database, option-file, components, bulk amounts, P-T axes, phase exclusion, and title entry |
| Convex-Hull projects | `CONVEX -> PSVDRAW -> PNG` |
| 2D constrained minimisation | `VERTEX -> PSSECT -> PNG` |
| Figure handling | Console log, zoomable PNG preview, and Save As |
| Phase exclusion | Database-aware raw and derived/endmember checklist |
| Installation safety | Runs are staged outside the original Perple_X installation |

## Current limits

Only the two calculation routes above are automated. The following controls are
visible for planning but are **not implemented** in generated projects yet:

- Component transformations
- Independent chemical potentials, activities, or fugacities
- Solution-model selection and editing
- Remaining BUILD calculation modes
- WERAMI data extraction and isopleth workflows

The application reports unsupported settings instead of silently creating
invalid Perple_X input.

## Intended workflow

```text
Project settings -> BUILD project (.dat) -> CONVEX or VERTEX -> PSVDRAW or PSSECT -> PNG preview
```

## Documentation

- [Installation guide](docs/installation.md)
- [Perple_X workflow notes](docs/perplex_workflow.md)
- [Perple_X 7.2.5 installation notes](docs/perplex_7_2_5_installation.md)
- [Development roadmap](docs/roadmap.md)
- [File formats and sample-data guidance](docs/file_formats.md)

## Development

Requires Python 3.12 or newer. For test and lint tools:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Contributing and data policy

Please do not commit Perple_X executables, thermodynamic databases,
solution-model files, unpublished sample data, local `.dat` projects, or
generated results unless their licence and scientific-data status explicitly
allow redistribution. Anonymised, reproducible examples belong under
`examples/` with an explanation of their provenance and expected output.

## License

This project is distributed under the [MIT License](LICENSE).
