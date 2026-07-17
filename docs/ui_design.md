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

The initial PySide6 window provides an installation-folder chooser, a `.dat` project chooser, a `Run CONVEX` button, a live console log, an automatic figure preview, and `Save Figure As…`. It stages every run under the system temporary directory (`PerpleXStudio/runs`), leaving the selected source project and Perple_X distribution unchanged. For the verified reference workflow, it automatically runs CONVEX, PSVDRAW, and Ghostscript to show the resulting PNG. The figure can be saved as PNG or its native PostScript output, and the scrollable preview supports zooming from 20% to 500%.
