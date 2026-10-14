# UI design

## First screen

The initial application window should have a project sidebar, a main workspace, and a persistent run log.

```text
+------------------+------------------------------------------+
| Project          | Calculation                              |
| - Inputs         | Perple_X folder: [ browse ]              |
| - Runs           | BUILD input:    [ browse ]              |
| - Results        |                                          |
|                  | [ Run BUILD ]                            |
|                  +------------------------------------------+
|                  | Console                                  |
|                  | > captured BUILD output                  |
+------------------+------------------------------------------+
```

## Interaction rules

- Disable Run until the executable location and input file are valid.
- Show the exact command, working directory, start/end time, and exit code.
- Keep raw output selectable and exportable.
- Do not claim calculation progress unless it can be derived reliably from program output.

## Implemented first window

The PySide6 window provides an installation-folder chooser, a `.dat` project chooser, calculation controls, a live console log, a figure preview, and `Save Figure As…`. It stages every run under the system temporary directory (`PerpleXStudio/runs`), leaving the selected source project and Perple_X distribution unchanged. It converts Perple_X's structured EPS output to SVG and renders that SVG directly with Qt, without Ghostscript or a raster preview. Studio edits (paths, phase overlays, and text boxes) are painted as vector geometry over the SVG. The figure can be saved as SVG, PNG, or its original PostScript output, and the scrollable preview supports zooming from 20% to 500%.
