# Observed Perple_X 7.2.5 Windows distribution

The reference installation provided for development is located outside this repository and must never be modified by Studio.

## Layout

```text
Perple_X_v7.2.5_Windows_64_gfortran/
  bin/          executable programs
  datafiles/    thermodynamic databases and solution-model data
  optionfiles/  Perple_X run-time and plotting options
  matlab_scripts/
  src/          Fortran source distribution
```

## Executables present

The distribution includes `build.exe`, `convex.exe`, `vertex.exe`, `werami.exe`, `pssect.exe`, `psvdraw.exe`, `meemum.exe`, and several specialised tools. Studio validates BUILD, CONVEX, VERTEX, and WERAMI. The supplied reference project is successfully calculated by CONVEX.

## Data and options

`datafiles/` contains multiple thermodynamic databases (including `hp622ver.dat`, `hp633ver.dat`, and `stx24ver.dat`) and solution-model files such as `solution_model.dat` and `stx24_solution_model.dat`.

`optionfiles/perplex_option.dat` documents run-time options. Its header says “Run-time Perple_X 7.1.10 options,” despite the supplied distribution being labelled 7.2.5. The user interface must therefore identify an installation primarily from the selected path and its file inventory; it must not present the option-file header as a verified package version.

## Integration rules

- Never run an executable in the installation directory.
- Do not copy or redistribute executables, databases, or solution-model files by default.
- Each Studio project will run in its own working directory and record the exact source installation path.
- The first actual execution test uses the provided `my_project.dat` reference project in a new, isolated run directory.
