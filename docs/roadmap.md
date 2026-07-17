# Roadmap

## Milestone 0 — Evidence and conventions

Collect a small, licence-safe reference set: successful BUILD inputs and their full generated outputs, one known failure, the Perple_X version, and notes on each interactive prompt. Document the observed files before writing parsers or input generators.

## Milestone 1 — Configure an installation and run CONVEX

Create/open a Studio project, configure the Perple_X installation, select an existing BUILD output (`.dat`), run CONVEX in an isolated project work directory, and display/save the console transcript and exit status. BUILD is an interactive input-authoring program: a pre-existing `.dat` is its output, so it must not be passed to BUILD as an input. The supplied type-1 reference project requires CONVEX and verifies this path.

## Milestone 2 — Support other calculation engines

Add VERTEX and other applicable Perple_X engine execution, result-file inventory, cancellation, diagnostics, and project-history records.

## Milestone 3 — Inspect WERAMI results

Launch WERAMI from a selected calculation and read its tabular results into a simple results viewer.

## Milestone 4 — Plot and export

Provide an interactive pseudosection viewer, phase highlighting, point inspection, and publication-oriented export.

## Later milestones

Guided input authoring, isopleths, P–T paths, batch calculations, comparison views, reports, and configurable diagnostic knowledge.
