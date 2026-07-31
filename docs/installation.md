# PerpleX Studio installation guide (Windows)

> **Experimental software:** confirm every generated Perple_X input and result
> independently. This application is not yet validated for research,
> publication, or production workflows.

PerpleX Studio is a graphical front end for Perple_X. It does not contain the
Perple_X engine, databases, or solution-model files: install Perple_X separately
and select its installation folder in Studio.

## Requirements

- Windows 10 or 11 (64-bit)
- Python 3.12 or newer
- A Windows 64-bit Perple_X installation, for example Perple_X 7.2.5
- 64-bit Ghostscript (currently required to make the PNG figure preview)
- PerpleX Studio source code from this repository

## Install Python

Install Python from [python.org](https://www.python.org/downloads/windows/),
selecting **Add Python to PATH** in the installer. Confirm it in PowerShell:

```powershell
python --version
```

## Install Perple_X

Extract Perple_X somewhere outside the Studio folder, for example:

```text
C:\Perple_X\Perple_X_v7.2.5_Windows_64_gfortran\
```

Select this **root folder** in Studio, not its `bin` subfolder. Studio expects:

```text
Perple_X_v7.2.5_Windows_64_gfortran\
  bin\build.exe, convex.exe, vertex.exe, psvdraw.exe, pssect.exe, werami.exe
  datafiles\
  optionfiles\
```

Studio copies required files to a separate run folder and does not change the
original Perple_X installation.

## Install Ghostscript

Install 64-bit Ghostscript from
[ghostscript.com](https://www.ghostscript.com/releases/gsdnld.html). Studio
normally detects `gswin64c.exe` after it is installed and restarted.

## Download and install Studio

Either clone the repository:

```powershell
git clone https://github.com/tualnwza-byte/PerpleX-Studio.git
cd PerpleX-Studio
```

or choose **Code > Download ZIP** from the repository page, extract it, and
open PowerShell in the extracted `PerpleX-Studio` folder.

Create an environment and install the app:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

If PowerShell blocks activation, run this in the current PowerShell window,
then repeat the activation command:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Start Studio:

```powershell
perplex-studio
```

If that command is unavailable, run:

```powershell
python -m perplex_studio.app
```

## First calculation

1. In **Run and Figure**, browse to the Perple_X installation root.
2. Open **Build Input**, choose a project name/folder, database, and
   `perplex_option.dat`.
3. Choose a calculation mode.
   - Mode 1: `CONVEX -> PSVDRAW -> PNG`
   - Mode 2: `VERTEX -> PSSECT -> PNG`
4. For mode 2, select all thermodynamic components and give every selected
   component a positive bulk amount. Relative values do not need normalising.
5. Set the P-T range. Studio defaults to `T(K)` on X and `P(bar)` on Y.
6. Click **Create .dat Project**, then **Run Perple_X Calculation**.
7. Review the console and figure preview; use **Save Figure As** to keep a PNG.

## Current limits

Only modes 1 and 2 are automated in this release. Component transformations,
independent chemical potentials, and solution-model selection are not yet
written into generated `.dat` files. Studio reports these limits rather than
creating invalid Perple_X input.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Invalid Perple_X installation | Select the root folder, not `bin`; confirm the executable, `datafiles`, and `optionfiles` folders exist. |
| Ghostscript not found | Install 64-bit Ghostscript and restart Studio. |
| VERTEX says all components must be constrained | In mode 2, enter a positive bulk amount for every selected component. |
| Figure has one field or colour | Check bulk composition, P-T range, database, and solution models. A successful calculation can contain one stable assemblage. |
| Perple_X reports an error but exit code is 0 | Read Studio's console. Some Perple_X programs return code 0 after writing `**error`. |

Always validate modelling decisions against the appropriate Perple_X
documentation, rock composition, observed assemblage, and solution models.
