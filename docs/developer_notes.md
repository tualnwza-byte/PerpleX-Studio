# Developer notes

## Conventions

- Put application code under `src/perplex_studio`.
- Keep UI, subprocess execution, parsing, and plotting separate.
- Add a test whenever a real Perple_X behaviour is understood.
- Preserve raw external-program output; interpretations are supplementary.
- Make paths portable with `pathlib`.

## Immediate next task

Build the Milestone 1 GUI only after at least one working Perple_X fixture is available. Until then, avoid guessing the BUILD dialogue or file semantics.
