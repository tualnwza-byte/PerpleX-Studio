"""Data-driven BUILD editor support.

The editor reads component and standard-variable declarations from a selected
thermodynamic database.  It deliberately keeps the user's BUILD choices in a
Studio setup file until a calculation-type-specific .dat writer is verified.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatabasePhase:
    """A real pure/endmember phase defined in a thermodynamic database."""

    name: str
    components: tuple[str, ...]
    derived: bool = False
    formula: str = ""
    make_reaction: str = ""


# Common Perple_X abbreviations documented in the supplied HP02 and SUPCRT92
# abbreviation references. Unknown or database-specific names are deliberately
# left blank instead of guessed.
_PHASE_FULL_NAMES = {
    "ab": "Albite",
    "acm": "Acmite",
    "ak": "Akermanite",
    "alm": "Almandine",
    "and": "Andalusite",
    "andr": "Andradite",
    "an": "Anorthite",
    "anth": "Anthophyllite",
    "atg": "Antigorite",
    "bi": "Biotite",
    "br": "Brucite",
    "cc": "Calcite",
    "cel": "Celadonite",
    "chl": "Chlorite",
    "clin": "Clinochlore",
    "cor": "Corundum",
    "crd": "Cordierite",
    "cz": "Clinozoisite",
    "di": "Diopside",
    "dol": "Dolomite",
    "en": "Enstatite",
    "ep": "Epidote",
    "fa": "Fayalite",
    "fcel": "Fe-celadonite",
    "fctd": "Fe-chloritoid",
    "fep": "Fe-epidote",
    "fo": "Forsterite",
    "fs": "Ferrosilite",
    "geh": "Gehlenite",
    "gl": "Glaucophane",
    "gph": "Graphite",
    "gr": "Grossular",
    "gt": "Garnet",
    "hed": "Hedenbergite",
    "hem": "Hematite",
    "ilm": "Ilmenite",
    "jd": "Jadeite",
    "ky": "Kyanite",
    "law": "Lawsonite",
    "mctd": "Mg-chloritoid",
    "merw": "Merwinite",
    "mont": "Monticellite",
    "ms": "Muscovite",
    "mt": "Magnetite",
    "mu": "Muscovite",
    "pa": "Paragonite",
    "per": "Periclase",
    "phl": "Phlogopite",
    "prl": "Pyrophyllite",
    "py": "Pyrope",
    "q": "Quartz",
    "ru": "Rutile",
    "sill": "Sillimanite",
    "sp": "Spinel",
    "sph": "Sphene (titanite)",
    "spss": "Spessartine",
    "ta": "Talc",
    "teph": "Tephroite",
    "tr": "Tremolite",
    "wo": "Wollastonite",
    "zo": "Zoisite",
    "zrc": "Zircon",
}


def phase_full_name(abbreviation: str) -> str:
    """Return a documented common phase name, or an empty string if unavailable."""
    return _PHASE_FULL_NAMES.get(abbreviation.casefold(), "")


@dataclass(frozen=True)
class ThermodynamicDatabase:
    path: Path
    components: tuple[str, ...]
    standard_variables: tuple[str, ...]
    pure_phases: tuple[DatabasePhase, ...]


def _section_entries(path: Path, start: str, end: str) -> tuple[str, ...]:
    entries: list[str] = []
    inside = False
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith(start):
            inside = True
            continue
        if line.startswith(end):
            break
        if inside and line and not line.startswith("|"):
            entries.append(line.split()[0])
    return tuple(entries)


def read_database(path: str | Path) -> ThermodynamicDatabase:
    """Read component names and standard variables from a Perple_X database."""
    database_path = Path(path).expanduser().resolve()
    if not database_path.is_file():
        raise ValueError(f"Thermodynamic database was not found: {database_path}")
    components = _section_entries(database_path, "begin_components", "end_components")
    variables = _section_entries(
        database_path, "begin_standard_variables", "end_standard_variables"
    )
    if not components:
        raise ValueError(f"No thermodynamic components found in: {database_path.name}")
    return ThermodynamicDatabase(
        database_path,
        components,
        variables,
        _read_pure_phases(database_path, components),
    )


def _read_pure_phases(path: Path, components: tuple[str, ...]) -> tuple[DatabasePhase, ...]:
    """Extract raw and made phase/endmember entries with component requirements."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    phase_header = re.compile(r"^\s*(\S+)\s+eos\s*=", re.IGNORECASE)
    make_definition = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]*)\s*=\s*(.+)$")
    component_set = set(components)
    phases: list[DatabasePhase] = []
    make_relations: dict[str, tuple[str, ...]] = {}
    make_reactions: dict[str, str] = {}
    make_names: list[str] = []
    inside_makes = False
    past_makes = False
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.lower().startswith("begin_makes"):
            inside_makes = True
            continue
        if stripped.lower().startswith("end_makes"):
            inside_makes = False
            past_makes = True
            continue
        if inside_makes:
            definition = make_definition.match(raw_line.split("|", maxsplit=1)[0])
            if definition is not None:
                name = definition.group(1)
                references = tuple(
                    token for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", definition.group(2))
                    if token.casefold() != name.casefold()
                )
                key = name.casefold()
                if key not in make_relations:
                    make_names.append(name)
                make_relations[key] = references
                make_reactions[key] = f"{name} = {definition.group(2).strip()}"
            continue
        if not past_makes:
            continue
        match = phase_header.match(raw_line)
        if match is None:
            continue
        phase_components: tuple[str, ...] = ()
        phase_formula = ""
        for formula_line in lines[index + 1 :]:
            formula = formula_line.strip()
            if not formula or formula.startswith("|"):
                continue
            names = tuple(
                dict.fromkeys(
                    name.upper()
                    for name in re.findall(r"([A-Za-z][A-Za-z0-9]*)\s*\(", formula)
                    if name.upper() in component_set
                )
            )
            phase_components = names
            if phase_components:
                phase_formula = formula
                break
        if phase_components:
            phases.append(DatabasePhase(match.group(1), phase_components, formula=phase_formula))

    raw_components = {phase.name.casefold(): phase.components for phase in phases}

    def made_components(name: str, ancestors: frozenset[str] = frozenset()) -> tuple[str, ...]:
        key = name.casefold()
        if key in raw_components:
            return raw_components[key]
        if key in ancestors or key not in make_relations:
            return ()
        resolved: list[str] = []
        for reference in make_relations[key]:
            for component in made_components(reference, ancestors | {key}):
                if component not in resolved:
                    resolved.append(component)
        return tuple(resolved)

    known_names = set(raw_components)
    for name in make_names:
        if name.casefold() not in known_names:
            phases.append(
                DatabasePhase(
                    name,
                    made_components(name),
                    derived=True,
                    make_reaction=make_reactions.get(name.casefold(), ""),
                )
            )
    return tuple(phases)


@dataclass(frozen=True)
class BuildSetup:
    """Selections made in the Studio BUILD editor."""

    project_name: str
    database_file: str
    option_file: str
    transformation_requested: bool
    component_mode: str
    saturated_fluid: bool
    saturated_components: tuple[str, ...]
    saturated_component_constraint: bool
    independent_potentials: bool
    thermodynamic_components: tuple[str, ...]
    fluid_eos: str
    geothermal_gradient: bool
    diagram_type: str
    x_variable: str
    y_variable: str
    x_minimum: float
    x_maximum: float
    y_minimum: float
    y_maximum: float
    section_variable: str
    section_value: float
    print_file: bool
    exclude_phases: bool
    excluded_phase_names: tuple[str, ...]
    solution_models: bool
    title: str
    component_amounts: tuple[tuple[str, float], ...] = ()


def save_build_setup(setup: BuildSetup, destination: str | Path) -> Path:
    """Save a user-editable Studio BUILD setup without altering Perple_X files."""
    output = Path(destination).expanduser().resolve()
    if output.suffix != ".json":
        output = output.with_suffix(".json")
    output.write_text(json.dumps(asdict(setup), indent=2), encoding="utf-8")
    return output


def _eos_code(label: str) -> int:
    """Extract the Perple_X numerical EoS choice from an editor label."""
    return int(label.split("–", maxsplit=1)[0].strip())


def write_convex_section_dat(
    setup: BuildSetup, database: ThermodynamicDatabase, destination: str | Path
) -> Path:
    """Write a verified Convex-Hull or fixed-bulk 2-D BUILD definition."""
    if not (
        setup.component_mode.startswith("1 –") or setup.component_mode.startswith("2 –")
    ):
        raise ValueError(
            "Automatic .dat creation currently supports only Convex-Hull "
            "or constrained minimization on a 2D grid."
        )
    if setup.transformation_requested:
        raise ValueError("Component transformations are not implemented yet.")
    if setup.independent_potentials:
        raise ValueError("Independent chemical potentials are not implemented yet.")
    if setup.geothermal_gradient:
        raise ValueError("Geothermal-gradient dependencies are not implemented yet.")
    if not setup.thermodynamic_components:
        raise ValueError("Select at least one thermodynamic component.")
    if setup.x_minimum >= setup.x_maximum or setup.y_minimum >= setup.y_maximum:
        raise ValueError("Each axis minimum must be lower than its maximum.")

    output = Path(destination).expanduser().resolve()
    if output.suffix.lower() != ".dat":
        output = output.with_suffix(".dat")
    variable_indexes = {name: index + 1 for index, name in enumerate(database.standard_variables)}
    if setup.x_variable not in variable_indexes or setup.y_variable not in variable_indexes:
        raise ValueError("Select valid X and Y variables from the database.")
    axis_order = [variable_indexes[setup.x_variable], variable_indexes[setup.y_variable]]
    axis_order.extend(index for index in range(1, 6) if index not in axis_order)
    values_min = [0.0] * 5
    values_max = [0.0] * 5
    values_min[variable_indexes[setup.x_variable] - 1] = setup.x_minimum
    values_max[variable_indexes[setup.x_variable] - 1] = setup.x_maximum
    values_min[variable_indexes[setup.y_variable] - 1] = setup.y_minimum
    values_max[variable_indexes[setup.y_variable] - 1] = setup.y_maximum
    saturated = set(setup.saturated_components) if setup.saturated_fluid else set()
    thermo_components = [name for name in setup.thermodynamic_components if name not in saturated]
    if not thermo_components:
        raise ValueError("At least one selected component must remain thermodynamic, not saturated.")

    def values(numbers: list[float], comment: str) -> str:
        return " ".join(f"{value:12.5f}" for value in numbers) + f"     {comment}"

    calculation_type = 1 if setup.component_mode.startswith("1 –") else 5
    amounts = dict(setup.component_amounts)
    if calculation_type == 5:
        missing_amounts = [name for name in thermo_components if amounts.get(name, 0.0) <= 0.0]
        if missing_amounts:
            raise ValueError(
                "A constrained 2-D grid requires a positive bulk amount for every "
                f"selected thermodynamic component: {', '.join(missing_amounts)}."
            )
    lines = [
        f"{Path(setup.database_file).name}     thermodynamic data file",
        "print    | no_print suppresses print output"
        if setup.print_file
        else "no_print | print generates print output",
        "plot     | obsolete 6.8.4+",
        "                                             | solution model file, blank = none",
        setup.title or setup.project_name,
        f"{Path(setup.option_file).name}     | Perple_X option file",
        f"{calculation_type:5d} calculation type: 0- composition, 1- Schreinemakers, 2 - liquidus/solidus, 3- Mixed, 5- gridded min, 7- 1d fract, 8- gwash, 9- 2d fract, 10- 7 w/file input, 11- 9 w/file input, 12- 0d infiltration",
    ]
    lines.extend("    0 unused place holder, post 06" for _ in range(9))
    lines.extend((
        "    0 number component transformations",
        f"{len(database.components):5d} number of components in the data base",
        "    0 component amounts, 0 - mole, 1 mass",
        "    0 unused place holder, post 06",
        "    0 unused place holder, post 06",
        "    0 unused place holder, post 05",
        f"{_eos_code(setup.fluid_eos):5d} ifug EoS for saturated phase",
        "    2 gridded minimization dimension (1 or 2)",
        "    0 special dependencies: 0 - P and T independent, 1 - P(T), 2 - T(P)",
        " 0.00000      0.00000      0.00000      0.00000      0.00000     Geothermal gradient polynomial coeffs.",
        "",
        "begin thermodynamic component list",
    ))
    for name in thermo_components:
        if calculation_type == 5:
            lines.append(
                f"{name:<5} 1  {amounts[name]:12.6g}      0.00000      0.00000     mole amount"
            )
        else:
            lines.append(f"{name:<5} 0  0.00000      0.00000      0.00000     unconstrained amount")
    lines.extend(("end thermodynamic component list", "", "begin saturated component list"))
    lines.extend(f"{name:<5} 0  0.00000      0.00000      0.00000     unconstrained amount" for name in sorted(saturated))
    lines.extend((
        "end saturated component list", "", "begin saturated phase component list",
        "end saturated phase component list", "", "begin independent potential/fugacity/activity list",
        "end independent potential list", "", "begin excluded phase list",
    ))
    if setup.exclude_phases:
        lines.extend(setup.excluded_phase_names)
    lines.extend(("end excluded phase list", "", "begin solution phase list", "end solution phase list", ""))
    lines.extend((
        values(values_max, "max p, t, xco2, mu_1, mu_2"),
        values(values_min, "min p, t, xco2, mu_1, mu_2"),
        values([0.0] * 5, "unused place holder post 06"),
        " ".join(f"{index:2d}" for index in axis_order[:5]) + "   indices of 1st & 2nd independent & sectioning variables",
        "",
    ))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
