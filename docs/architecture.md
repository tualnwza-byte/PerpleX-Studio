# Architecture

```text
Qt user interface
        |
application controllers
        |
project model ---- execution records ---- console logs
        |
Perple_X runner (subprocess, isolated working directory)
        |
BUILD / VERTEX / WERAMI executables
```

## Boundaries

The UI presents project state and results. Controllers validate requests and coordinate actions. The runner is the only layer allowed to invoke Perple_X processes. Parsers will read documented files into typed application models. Plotting consumes those models rather than raw files.

`perplex_installation.py` is the configuration boundary for a local Perple_X distribution. It validates the folder without copying, changing, or running anything in it.

## Project data

Each Studio project will preserve its original user inputs, a copy or reference to the Perple_X configuration, execution logs, command metadata, and generated outputs. No result should overwrite its originating input.

## Technology direction

Python 3.12+, PySide6, standard-library `subprocess`, and pytest. Matplotlib or pyqtgraph will be chosen after assessing actual output formats and interaction needs.
