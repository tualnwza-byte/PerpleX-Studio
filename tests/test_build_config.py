from pathlib import Path

from perplex_studio.build_config import (
    BuildSetup,
    phase_full_name,
    read_database,
    write_convex_section_dat,
)


def test_read_database_extracts_components_and_standard_variables(tmp_path: Path) -> None:
    database = tmp_path / "demo.dat"
    database.write_text(
        "begin_standard_variables\nP(bar) 1.0\nT(K) 298.15\nend_standard_variables\n"
        "begin_components\nSIO2 60.08\nH2O 18.01\nend_components\n",
        encoding="utf-8",
    )

    parsed = read_database(database)

    assert parsed.components == ("SIO2", "H2O")
    assert parsed.standard_variables == ("P(bar)", "T(K)")


def test_read_database_extracts_phase_component_requirements(tmp_path: Path) -> None:
    database = tmp_path / "demo.dat"
    database.write_text(
        "begin_standard_variables\nP(bar) 1.0\nT(K) 298.15\nend_standard_variables\n"
        "begin_components\nSIO2 60.08\nMGO 40.30\nCAO 56.08\nCO2 44.01\nend_components\n"
        "begin_makes\nend_makes\n"
        "q EoS = 2\nSIO2(1)\nend\n\n"
        "fo EoS = 2\nMGO(2)SIO2(1)\nend\n\n"
        "cc EoS = 2\nCAO(1)CO2(1)\nend\n",
        encoding="utf-8",
    )

    parsed = read_database(database)

    assert [(phase.name, phase.components) for phase in parsed.pure_phases] == [
        ("q", ("SIO2",)),
        ("fo", ("MGO", "SIO2")),
        ("cc", ("CAO", "CO2")),
    ]


def test_read_database_includes_made_endmembers(tmp_path: Path) -> None:
    database = tmp_path / "demo.dat"
    database.write_text(
        "begin_standard_variables\nP(bar) 1.0\nT(K) 298.15\nend_standard_variables\n"
        "begin_components\nSIO2 60.08\nend_components\n"
        "begin_makes\nsil8L = 8/5 silL\nend_makes\n"
        "silL EoS = 2\nSIO2(1)\nend\n",
        encoding="utf-8",
    )

    parsed = read_database(database)

    assert [(phase.name, phase.components, phase.derived) for phase in parsed.pure_phases] == [
        ("silL", ("SIO2",), False),
        ("sil8L", ("SIO2",), True),
    ]
    assert parsed.pure_phases[0].formula == "SIO2(1)"
    assert parsed.pure_phases[1].make_reaction == "sil8L = 8/5 silL"


def test_phase_full_name_uses_known_abbreviations_without_guessing_unknown_names() -> None:
    assert phase_full_name("fo") == "Forsterite"
    assert phase_full_name("unknown_phase") == ""


def test_write_convex_section_dat_creates_a_named_project(tmp_path: Path) -> None:
    database = tmp_path / "demo.dat"
    database.write_text(
        "begin_standard_variables\nP(bar) 1.0\nT(K) 298.15\nend_standard_variables\n"
        "begin_components\nSIO2 60.08\nH2O 18.01\nend_components\n",
        encoding="utf-8",
    )
    parsed = read_database(database)
    setup = BuildSetup(
        "demo", "demo.dat", "perplex_option.dat", False, "1 – Convex-Hull minimization",
        False, (), False, False, ("SIO2",), "0 – X(CO2) H2O-CO2 MRK (DeSantis et al. 1974)",
        False, "2 – Sections and Schreinemakers-type diagrams", "T(K)", "P(bar)",
        500.0, 1600.0, 1000.0, 5000.0, "Y(CO2)", 0.0, False, False, (), False, "",
    )

    output = write_convex_section_dat(setup, parsed, tmp_path / "demo.dat")

    assert output.is_file()
    text = output.read_text(encoding="utf-8")
    assert "demo.dat     thermodynamic data file" in text
    assert "SIO2" in text


def test_write_grid_section_requires_and_writes_bulk_amounts(tmp_path: Path) -> None:
    database = tmp_path / "demo.dat"
    database.write_text(
        "begin_standard_variables\nP(bar) 1.0\nT(K) 298.15\nend_standard_variables\n"
        "begin_components\nSIO2 60.08\nH2O 18.01\nend_components\n",
        encoding="utf-8",
    )
    setup = BuildSetup(
        "grid", "demo.dat", "perplex_option.dat", False,
        "2 – Constrained minimization on a 2d grid [default]", False, (), False,
        False, ("SIO2",), "0 – X(CO2) H2O-CO2 MRK (DeSantis et al. 1974)",
        False, "2 – Sections and Schreinemakers-type diagrams", "T(K)", "P(bar)",
        500.0, 1600.0, 1000.0, 5000.0, "Y(CO2)", 0.0, False, False, (), False,
        "", (("SIO2", 2.5),),
    )

    output = write_convex_section_dat(setup, read_database(database), tmp_path / "grid.dat")

    text = output.read_text(encoding="utf-8")
    assert text.splitlines()[6].lstrip().startswith("5 calculation type")
    assert "SIO2  1" in text
    assert "2.5" in text
