# Vision

PerpleX Studio should let a geoscientist create reproducible Perple_X calculations without having to memorise interactive prompts, manage opaque intermediate files, or interpret cryptic errors unaided.

## Product principles

- Perple_X remains the calculation engine and source of scientific results.
- User-facing choices use petrological language; advanced controls remain available without crowding the standard workflow.
- Every calculation is reproducible: inputs, executable version, console output, and generated files are kept with the project.
- The application must never silently alter a bulk composition, database, solution-model set, or Perple_X option.
- Errors retain the original console output and add actionable explanations where possible.

## Initial audience

Graduate students and researchers running common Perple_X pseudosection workflows on Windows. The architecture should remain portable to macOS and Linux.

## Non-goals for the first release

- Reimplementing Gibbs-energy minimisation.
- Bundling third-party databases or executables without explicit redistribution permission.
- Replacing every Perple_X program or supporting every calculation type at launch.
