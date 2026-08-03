# Perple_X workflow notes

This document records observed behaviour, not assumptions. It will be expanded from real example projects.

The currently configured reference is the Windows 64-bit gfortran Perple_X 7.2.5 distribution. Its observed layout and safeguards are recorded in [the installation notes](perplex_7_2_5_installation.md).

## Target first workflow

```text
Interactive BUILD session
        -> project definition (*.dat)
        -> CONVEX (verified reference workflow)
        -> stable assemblage output
        -> WERAMI
        -> tabulated data / visualisation
```

## Questions to resolve from reference projects

1. Which BUILD prompts and generated files vary by calculation type?
2. Which files are required by VERTEX and WERAMI for each Perple_X version?
3. Which working-directory assumptions and executable names matter on Windows?
4. Which console messages indicate progress, warnings, recoverable errors, and failures?
5. Which option-file settings should be visible in the first UI?

## Scope discipline

Version 0.1 stages a known-good BUILD output unchanged and runs CONVEX. It must faithfully capture the process output before Studio attempts to generate or edit BUILD input itself. Additional engines, including VERTEX, will be introduced only against verified fixtures.
