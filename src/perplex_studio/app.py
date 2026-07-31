"""PySide6 desktop application entry point."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from shutil import copy2
from tempfile import gettempdir

from perplex_studio.build_config import (
    BuildSetup,
    read_database,
    save_build_setup,
    write_convex_section_dat,
)
from perplex_studio.perplex_installation import PerpleXInstallation
from perplex_studio.runner import (
    StagedProject,
    calculation_type,
    find_ghostscript,
    stage_project,
)


def main() -> None:
    """Start the PerpleX Studio desktop application."""
    try:
        from PySide6.QtCore import QLocale, QProcess, QSettings, Qt
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import (
            QApplication,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QCheckBox,
            QComboBox,
            QDoubleSpinBox,
            QGroupBox,
            QGridLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QPlainTextEdit,
            QTableWidget,
            QTableWidgetItem,
            QScrollArea,
            QStatusBar,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as error:
        raise SystemExit(
            "PySide6 is required. Activate the project environment and run: "
            'pip install -e ".[dev]"'
        ) from error

    class BuildEditor(QWidget):
        """Input editor for the initial, data-driven BUILD workflow."""

        component_modes = (
            "1 – Convex-Hull minimization",
            "2 – Constrained minimization on a 2d grid [default]",
            "3 – Constrained minimization on a 1d grid",
            "4 – Output pseudocompound data",
            "5 – 1-d Phase fractionation",
            "6 – 0-d Infiltration-reaction-fractionation",
            "7 – 2-d Phase fractionation (FRAC2D/TITRATE)",
            "8 – (pseudo-)Ternary liquidus/solidus surfaces",
        )
        fluid_eos_options = (
            "0 – X(CO2) H2O-CO2 MRK (DeSantis et al. 1974)",
            "1 – X(CO2) H2O-CO2 HSMRK (Kerrick & Jacobs 1981)",
            "2 – X(CO2) H2O-CO2 MRK hybrid-EoS",
            "5 – X(CO2) H2O-CO2 CORK (Holland & Powell)",
            "8 – f(O2/CO2) C-buffered COH MRK hybrid-EoS",
            "10 – X(O) C-buffered COH MRK hybrid-EoS",
            "12 – X(O)-f(S2) C-buffered COHS MRK hybrid-EoS",
            "13 – X(H2) H2O-H2 MRK hybrid-EoS",
            "14 – X(CO2) H2O-CO2 Pitzer & Sterner",
            "15 – X(H2) H2O-H2 low-T MRK hybrid-EoS",
            "19 – X(O)-X(S) C-buffered COHS MRK hybrid-EoS",
            "20 – X(O)-X(C) COHS MRK hybrid-EoS",
            "24 – f(O2/CO2)-N/C C-buffered COHN MRK hybrid-EoS",
            "25 – X(CO2)-X(NaCl) H2O-CO2-NaCl",
            "27 – X(O)-X(C) C-O-H MRK hybrid-EoS",
        )

        def __init__(self, installation_edit: QLineEdit, project_created: object | None = None) -> None:
            super().__init__()
            self.installation_edit = installation_edit
            self.project_created = project_created
            self.database: object | None = None
            self.project_name = QLineEdit("my_project")
            self.project_directory = QLineEdit(str(Path.cwd()))
            self.project_directory_button = QPushButton("Browse…")
            self.project_directory_button.clicked.connect(self._choose_project_directory)
            self.database_menu = QComboBox()
            self.option_menu = QComboBox()
            self.transform = QCheckBox("Transform/change database components (planned)")
            self.transform.setChecked(False)
            self.transform.setEnabled(False)
            self.transform.setToolTip(
                "Component transformations need a user-defined transformation matrix and "
                "are not available in this version of PerpleX Studio yet."
            )
            self.component_mode = QComboBox()
            self.component_mode.addItems(self.component_modes)
            self.component_mode.setCurrentIndex(1)
            self.saturated_fluid = QCheckBox("Calculate with saturated fluid")
            self.saturated_component_constraint = QCheckBox("Calculations with saturated components")
            self.h2o = QCheckBox("H2O")
            self.co2 = QCheckBox("CO2")
            self.saturated_components = QListWidget()
            self.saturated_components.setMaximumHeight(130)
            self.independent_potentials = QCheckBox(
                "Use chemical potentials, activities, or fugacities as independent variables"
            )
            self.components = QListWidget()
            self.components.setMinimumHeight(150)
            self.components.setMaximumHeight(220)
            self._component_amounts: dict[str, float] = {}
            self.component_amount_table = QTableWidget(0, 2)
            self.component_amount_table.setHorizontalHeaderLabels(("Component", "Bulk amount (moles)"))
            self.component_amount_table.verticalHeader().setVisible(False)
            self.component_amount_table.setMaximumHeight(170)
            self.fluid_eos = QComboBox()
            self.fluid_eos.addItems(self.fluid_eos_options)
            self.geothermal_gradient = QCheckBox("Make P or T dependent along a geothermal gradient")
            self.diagram_type = QComboBox()
            self.diagram_type.addItems((
                "0 – Composition diagram",
                "1 – Mixed-variable diagram",
                "2 – Sections and Schreinemakers-type diagrams",
            ))
            self.diagram_type.setCurrentIndex(2)
            self.x_variable, self.y_variable, self.section_variable = QComboBox(), QComboBox(), QComboBox()
            self.x_minimum, self.x_maximum = self._number(), self._number()
            self.y_minimum, self.y_maximum = self._number(), self._number()
            self.section_value = self._number()
            self.print_file = QCheckBox("Write a print file")
            self.exclude_phases = QCheckBox("Exclude selected pure or endmember phases")
            self.phase_exclusions = QListWidget()
            self.phase_exclusions.setMinimumHeight(160)
            self.phase_exclusions.setMaximumHeight(260)
            self.phase_exclusion_help = QLabel(
                "Select components above to show compatible database phases. "
                "Only checked phases will be written to the Perple_X exclusion list."
            )
            self.phase_exclusion_help.setWordWrap(True)
            self.solution_models = QCheckBox("Include solution models")
            self.title = QLineEdit()
            self.save_button = QPushButton("Save BUILD setup…")
            self.save_button.clicked.connect(self._save_setup)
            self.create_dat_button = QPushButton("Create .dat Project")
            self.create_dat_button.clicked.connect(self._create_dat)

            root = QVBoxLayout(self)
            header = QLabel(
                "BUILD input editor — selections are saved as a Studio setup. "
                "Only verified project definitions should be run with Perple_X."
            )
            header.setWordWrap(True)
            root.addWidget(header)
            identity = QFormLayout()
            identity.addRow("Project/file name", self.project_name)
            directory_row = QWidget()
            directory_layout = QHBoxLayout(directory_row)
            directory_layout.setContentsMargins(0, 0, 0, 0)
            directory_layout.addWidget(self.project_directory, 1)
            directory_layout.addWidget(self.project_directory_button)
            identity.addRow("Project folder", directory_row)
            identity.addRow("Thermodynamic database", self.database_menu)
            identity.addRow("Computational option file", self.option_menu)
            identity.addRow("Specify components mode", self.component_mode)
            identity.addRow("Calculation title", self.title)
            root.addWidget(self._box("Project", identity))
            root.addWidget(self.transform)

            fluid = QGridLayout()
            fluid.addWidget(self.saturated_fluid, 0, 0, 1, 2)
            fluid.addWidget(self.h2o, 1, 0)
            fluid.addWidget(self.co2, 1, 1)
            fluid.addWidget(self.saturated_component_constraint, 2, 0, 1, 2)
            fluid.addWidget(QLabel("Select fewer than 6 saturated components"), 3, 0, 1, 2)
            fluid.addWidget(self.saturated_components, 4, 0, 1, 2)
            fluid.addWidget(QLabel("Saturated fluid EoS"), 5, 0)
            fluid.addWidget(self.fluid_eos, 5, 1)
            root.addWidget(self._box("Saturated fluid", fluid))

            root.addWidget(self.independent_potentials)
            components = QVBoxLayout()
            components.addWidget(QLabel("Select thermodynamic components from the selected database"))
            components.addWidget(self.components)
            self.bulk_amounts_box = QGroupBox("Bulk composition for constrained 2-D grid")
            bulk_amounts_layout = QVBoxLayout(self.bulk_amounts_box)
            bulk_amounts_layout.addWidget(QLabel(
                "Enter a positive amount for every selected component. Perple_X uses their relative values."
            ))
            bulk_amounts_layout.addWidget(self.component_amount_table)
            components.addWidget(self.bulk_amounts_box)
            root.addWidget(self._box("Thermodynamic components", components))

            axes = QGridLayout()
            axes.addWidget(self.geothermal_gradient, 0, 0, 1, 4)
            axes.addWidget(QLabel("Diagram type"), 1, 0)
            axes.addWidget(self.diagram_type, 1, 1, 1, 3)
            axes.addWidget(QLabel("X axis"), 2, 0)
            axes.addWidget(self.x_variable, 2, 1)
            axes.addWidget(QLabel("Min / max"), 2, 2)
            axes.addWidget(self.x_minimum, 2, 3)
            axes.addWidget(self.x_maximum, 2, 4)
            axes.addWidget(QLabel("Y axis"), 3, 0)
            axes.addWidget(self.y_variable, 3, 1)
            axes.addWidget(QLabel("Min / max"), 3, 2)
            axes.addWidget(self.y_minimum, 3, 3)
            axes.addWidget(self.y_maximum, 3, 4)
            axes.addWidget(QLabel("Sectioning variable / value"), 4, 0)
            axes.addWidget(self.section_variable, 4, 1)
            axes.addWidget(self.section_value, 4, 3)
            root.addWidget(self._box("Independent variables", axes))

            choices = QVBoxLayout()
            choices.addWidget(self.print_file)
            choices.addWidget(self.exclude_phases)
            choices.addWidget(self.phase_exclusion_help)
            choices.addWidget(self.phase_exclusions)
            choices.addWidget(self.solution_models)
            root.addWidget(self._box("Phases and models", choices))
            actions = QHBoxLayout()
            actions.addWidget(self.create_dat_button)
            actions.addWidget(self.save_button)
            actions.addStretch()
            root.addLayout(actions)
            root.addStretch()

            self.saturated_fluid.toggled.connect(self._set_fluid_enabled)
            self.exclude_phases.toggled.connect(self._set_phase_exclusions_enabled)
            self.database_menu.currentIndexChanged.connect(lambda _index: self._load_database())
            self.components.itemChanged.connect(lambda _item: self._sync_component_amounts())
            self.saturated_components.itemChanged.connect(
                lambda _item: self._sync_phase_exclusions(self._checked(self.components))
            )
            self.h2o.toggled.connect(
                lambda _enabled: self._sync_phase_exclusions(self._checked(self.components))
            )
            self.co2.toggled.connect(
                lambda _enabled: self._sync_phase_exclusions(self._checked(self.components))
            )
            self.component_mode.currentIndexChanged.connect(lambda _index: self._set_mode_widgets())
            self.installation_edit.editingFinished.connect(self.refresh_files)
            self._set_fluid_enabled(False)
            self._set_phase_exclusions_enabled(False)
            self._set_mode_widgets()

        @staticmethod
        def _number() -> QDoubleSpinBox:
            field = QDoubleSpinBox()
            # Perple_X input uses ASCII digits regardless of the Windows locale.
            field.setLocale(QLocale.c())
            field.setRange(-1.0e12, 1.0e12)
            field.setDecimals(6)
            field.setValue(0.0)
            return field

        @staticmethod
        def _box(title: str, layout: object) -> QGroupBox:
            box = QGroupBox(title)
            box.setLayout(layout)
            return box

        def refresh_files(self) -> None:
            try:
                installation = PerpleXInstallation.discover(self.installation_edit.text())
            except ValueError:
                return
            self.database_menu.blockSignals(True)
            self.database_menu.clear()
            for path in sorted(installation.datafiles_directory.glob("*.dat")):
                self.database_menu.addItem(path.name, path)
            self.option_menu.clear()
            for path in sorted(installation.optionfiles_directory.glob("*.dat")):
                self.option_menu.addItem(path.name, path)
            default_index = self.option_menu.findText("perplex_option.dat")
            self.option_menu.setCurrentIndex(max(0, default_index))
            self.database_menu.blockSignals(False)
            self._load_database()

        def _load_database(self) -> None:
            path = self.database_menu.currentData()
            if not isinstance(path, Path):
                return
            try:
                self.database = read_database(path)
            except ValueError:
                return
            for target in (self.components, self.saturated_components):
                target.clear()
                for name in self.database.components:
                    item = QListWidgetItem(name)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked)
                    target.addItem(item)
            self._component_amounts.clear()
            self._sync_component_amounts()
            for menu in (self.x_variable, self.y_variable, self.section_variable):
                menu.clear()
                menu.addItems(self.database.standard_variables)
            if self.database.standard_variables:
                x_index = self.x_variable.findText("T(K)")
                y_index = self.y_variable.findText("P(bar)")
                self.x_variable.setCurrentIndex(x_index if x_index >= 0 else 0)
                self.y_variable.setCurrentIndex(y_index if y_index >= 0 else min(1, len(self.database.standard_variables) - 1))

        def _set_mode_widgets(self) -> None:
            self.bulk_amounts_box.setVisible(self.component_mode.currentText().startswith("2 –"))

        def _sync_component_amounts(self) -> None:
            selected = self._checked(self.components)
            self.component_amount_table.setRowCount(0)
            for row, name in enumerate(selected):
                self.component_amount_table.insertRow(row)
                component = QTableWidgetItem(name)
                component.setFlags(component.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.component_amount_table.setItem(row, 0, component)
                amount = self._number()
                amount.setMinimum(0.0)
                amount.setValue(self._component_amounts.get(name, 0.0))
                amount.valueChanged.connect(
                    lambda value, component_name=name: self._component_amounts.__setitem__(
                        component_name, value
                    )
                )
                self.component_amount_table.setCellWidget(row, 1, amount)
            self._sync_phase_exclusions(selected)

        def _sync_phase_exclusions(self, selected_components: tuple[str, ...]) -> None:
            checked = set(self._checked(self.phase_exclusions))
            available = set(selected_components)
            if self.saturated_fluid.isChecked():
                available.update(self._checked(self.saturated_components))
                if self.h2o.isChecked():
                    available.add("H2O")
                if self.co2.isChecked():
                    available.add("CO2")
            self.phase_exclusions.clear()
            if self.database is None:
                return
            for phase in self.database.pure_phases:
                # With no components selected, expose the full database list.
                # Once the user selects components, narrow it to compatible phases.
                if not available or set(phase.components).issubset(available):
                    item = QListWidgetItem(
                        f"{phase.name}  —  {' + '.join(phase.components)}"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, phase.name)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked if phase.name in checked else Qt.CheckState.Unchecked
                    )
                    self.phase_exclusions.addItem(item)

        def _set_phase_exclusions_enabled(self, enabled: bool) -> None:
            self.phase_exclusions.setEnabled(enabled)
            self.phase_exclusion_help.setEnabled(enabled)

        def _set_fluid_enabled(self, enabled: bool) -> None:
            for control in (
                self.h2o,
                self.co2,
                self.saturated_component_constraint,
                self.saturated_components,
                self.fluid_eos,
            ):
                control.setEnabled(enabled)

        @staticmethod
        def _checked(widget: QListWidget) -> tuple[str, ...]:
            return tuple(
                widget.item(index).text()
                for index in range(widget.count())
                if widget.item(index).checkState() == Qt.CheckState.Checked
            )

        def _choose_project_directory(self) -> None:
            directory = QFileDialog.getExistingDirectory(
                self, "Select project folder", self.project_directory.text()
            )
            if directory:
                self.project_directory.setText(directory)

        def _collect_setup(self) -> BuildSetup | None:
            if self.database_menu.currentData() is None or self.option_menu.currentData() is None:
                QMessageBox.warning(self, "No database", "Select a valid Perple_X installation and database.")
                return None
            saturated = list(self._checked(self.saturated_components))
            if self.h2o.isChecked():
                saturated.append("H2O")
            if self.co2.isChecked():
                saturated.append("CO2")
            saturated = tuple(dict.fromkeys(saturated))
            if len(saturated) >= 6:
                QMessageBox.warning(self, "Too many saturated components", "Select fewer than 6 saturated components.")
                return None
            name = self.project_name.text().strip()
            if not name or any(character in name for character in " .\\/"):
                QMessageBox.warning(self, "Invalid project name", "Use a name without spaces, dots, or slashes.")
                return None
            return BuildSetup(
                project_name=name,
                database_file=self.database_menu.currentText(),
                option_file=self.option_menu.currentText(),
                transformation_requested=self.transform.isChecked(),
                component_mode=self.component_mode.currentText(),
                saturated_fluid=self.saturated_fluid.isChecked(),
                saturated_components=saturated,
                saturated_component_constraint=self.saturated_component_constraint.isChecked(),
                independent_potentials=self.independent_potentials.isChecked(),
                thermodynamic_components=self._checked(self.components),
                fluid_eos=self.fluid_eos.currentText(),
                geothermal_gradient=self.geothermal_gradient.isChecked(),
                diagram_type=self.diagram_type.currentText(),
                x_variable=self.x_variable.currentText(),
                y_variable=self.y_variable.currentText(),
                x_minimum=self.x_minimum.value(), x_maximum=self.x_maximum.value(),
                y_minimum=self.y_minimum.value(), y_maximum=self.y_maximum.value(),
                section_variable=self.section_variable.currentText(),
                section_value=self.section_value.value(),
                print_file=self.print_file.isChecked(),
                exclude_phases=self.exclude_phases.isChecked(),
                excluded_phase_names=tuple(
                    self.phase_exclusions.item(index).data(Qt.ItemDataRole.UserRole)
                    for index in range(self.phase_exclusions.count())
                    if self.phase_exclusions.item(index).checkState() == Qt.CheckState.Checked
                ),
                solution_models=self.solution_models.isChecked(),
                title=self.title.text(),
                component_amounts=tuple(
                    (component, self._component_amounts.get(component, 0.0))
                    for component in self._checked(self.components)
                ),
            )

        def _save_setup(self) -> None:
            setup = self._collect_setup()
            if setup is None:
                return
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save Studio BUILD setup",
                f"{setup.project_name}.perplex-studio.json",
                "Studio setup (*.json)",
            )
            if filename:
                saved = save_build_setup(setup, filename)
                QMessageBox.information(self, "BUILD setup saved", f"Saved: {saved}")

        def _create_dat(self) -> None:
            setup = self._collect_setup()
            if setup is None:
                return
            if self.database is None:
                QMessageBox.warning(self, "No database", "Select a valid thermodynamic database.")
                return
            database = self.database
            folder = Path(self.project_directory.text()).expanduser()
            if not folder.is_dir():
                QMessageBox.warning(self, "Invalid project folder", "Select an existing project folder.")
                return
            output = folder / f"{setup.project_name}.dat"
            if output.exists():
                answer = QMessageBox.question(
                    self, "Replace project?", f"{output.name} already exists. Replace it?"
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            try:
                created = write_convex_section_dat(setup, database, output)
            except ValueError as error:
                QMessageBox.warning(self, "Cannot create .dat project", str(error))
                return
            QMessageBox.information(self, "Perple_X project created", f"Created: {created}")
            if callable(self.project_created):
                self.project_created(created)

    class MainWindow(QMainWindow):
        """Interface for running staged Perple_X Convex-Hull and grid projects."""

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("PerpleX Studio")
            self.resize(920, 640)
            self.setStyleSheet(
                """
                QMainWindow { background: #ffffff; color: #2e1065; }
                QWidget { background: #ffffff; color: #2e1065; font-size: 13px; }
                QTabWidget::pane {
                    background: #faf5ff; border: 1px solid #c4b5fd; border-radius: 6px;
                }
                QTabBar::tab {
                    background: #ede9fe; border: 1px solid #c4b5fd; border-bottom: none;
                    color: #4c1d95; padding: 8px 16px; margin-right: 3px; font-weight: 600;
                }
                QTabBar::tab:selected { background: #ffffff; color: #6d28d9; }
                QGroupBox {
                    background: #ffffff; border: 1px solid #c4b5fd; border-radius: 7px;
                    margin-top: 14px; padding: 14px 10px 10px 10px; font-weight: 700;
                    color: #2e1065;
                }
                QGroupBox::title {
                    subcontrol-origin: margin; left: 12px; padding: 0 6px;
                    color: #6d28d9; background: #ffffff;
                }
                QLineEdit, QComboBox, QDoubleSpinBox, QListWidget, QPlainTextEdit {
                    background: #ffffff; border: 1px solid #a78bfa; border-radius: 4px;
                    color: #2e1065; min-height: 26px; padding: 2px 6px;
                }
                QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QListWidget:focus {
                    border: 2px solid #7c3aed; background: #faf5ff;
                }
                QComboBox::drop-down { border-left: 1px solid #c4b5fd; width: 24px; }
                QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #a78bfa; }
                QListWidget::item { padding: 4px; }
                QListWidget::item:selected { background: #ede9fe; color: #2e1065; }
                QCheckBox {
                    background: #faf5ff; border: 1px solid #c4b5fd; border-radius: 4px;
                    spacing: 7px; padding: 5px 8px;
                }
                QCheckBox:hover { background: #f3e8ff; border-color: #7c3aed; }
                QCheckBox:checked { background: #ede9fe; border-color: #6d28d9; font-weight: 600; }
                QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #7e22ce; background: #ffffff; }
                QCheckBox::indicator:checked { background: #6d28d9; border-color: #581c87; }
                QListWidget::indicator { width: 16px; height: 16px; border: 1px solid #7e22ce; background: #ffffff; }
                QListWidget::indicator:checked { background: #6d28d9; border-color: #581c87; }
                QPushButton {
                    background: #6d28d9; color: #ffffff; border: 1px solid #581c87;
                    border-radius: 4px; padding: 7px 12px; font-weight: 700;
                }
                QPushButton:hover { background: #5b21b6; }
                QPushButton:pressed { background: #4c1d95; }
                QPushButton:disabled { background: #ddd6fe; color: #6b21a8; border-color: #c4b5fd; }
                QScrollArea, QScrollArea::viewport { background: #ffffff; border: none; }
                QStatusBar { background: #2e1065; color: #ffffff; }
                """
            )
            self._settings = QSettings("PerpleX Studio", "PerpleX Studio")
            self._process: QProcess | None = None
            self._staged_project: StagedProject | None = None
            self._installation: PerpleXInstallation | None = None
            self._ghostscript: Path | None = None
            self._stage = ""
            self._stage_had_perplex_error = False
            self._figure_pixmap: QPixmap | None = None
            self._zoom_factor = 1.0

            self.installation_edit = QLineEdit(
                self._settings.value("installation_path", "", type=str)
            )
            self.project_edit = QLineEdit(self._settings.value("project_path", "", type=str))
            self.run_button = QPushButton("Run Perple_X Calculation")
            self.run_button.clicked.connect(self._run_convex)
            self.save_figure_button = QPushButton("Save Figure As…")
            self.save_figure_button.setEnabled(False)
            self.save_figure_button.clicked.connect(self._save_figure_as)
            self.zoom_out_button = QPushButton("Zoom Out")
            self.zoom_out_button.clicked.connect(lambda: self._change_zoom(0.8))
            self.zoom_in_button = QPushButton("Zoom In")
            self.zoom_in_button.clicked.connect(lambda: self._change_zoom(1.25))
            self.reset_zoom_button = QPushButton("Reset Zoom")
            self.reset_zoom_button.clicked.connect(self._reset_zoom)
            for button in (self.zoom_out_button, self.zoom_in_button, self.reset_zoom_button):
                button.setEnabled(False)
            self.log = QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setPlaceholderText("Perple_X console output will appear here.")
            self.figure = QLabel("The generated pseudosection preview will appear here.")
            self.figure.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.figure.setStyleSheet("QLabel { background: white; color: #52606d; }")
            self.figure_scroll = QScrollArea()
            self.figure_scroll.setStyleSheet("QScrollArea { background: white; border: 1px solid #d9e2ec; }")
            self.figure_scroll.setBackgroundRole(self.figure.backgroundRole())
            self.figure_scroll.setWidget(self.figure)
            self.figure_scroll.setWidgetResizable(False)
            self.figure_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self.build_editor = BuildEditor(self.installation_edit, self._use_created_project)
            self.build_editor.refresh_files()

            form = QFormLayout()
            form.addRow("Perple_X installation", self._path_row(self.installation_edit, self._choose_installation))
            form.addRow("Project definition (.dat)", self._path_row(self.project_edit, self._choose_project))

            layout = QVBoxLayout()
            layout.addLayout(form)
            actions = QHBoxLayout()
            actions.addWidget(self.run_button)
            actions.addWidget(self.save_figure_button)
            actions.addStretch()
            layout.addLayout(actions)
            layout.addWidget(QLabel("Console"))
            layout.addWidget(self.log, 1)
            figure_header = QHBoxLayout()
            figure_header.addWidget(QLabel("Figure preview"))
            figure_header.addStretch()
            figure_header.addWidget(self.zoom_out_button)
            figure_header.addWidget(self.zoom_in_button)
            figure_header.addWidget(self.reset_zoom_button)
            layout.addLayout(figure_header)
            layout.addWidget(self.figure_scroll, 2)
            run_page = QWidget()
            run_page.setLayout(layout)
            run_scroll = QScrollArea()
            run_scroll.setWidget(run_page)
            run_scroll.setWidgetResizable(True)
            run_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            build_scroll = QScrollArea()
            build_scroll.setWidget(self.build_editor)
            build_scroll.setWidgetResizable(True)
            build_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.tabs = QTabWidget()
            self.tabs.addTab(build_scroll, "Build Input")
            self.tabs.addTab(run_scroll, "Run and Figure")
            self.setCentralWidget(self.tabs)
            self.setStatusBar(QStatusBar())
            self.statusBar().showMessage("Select a Perple_X installation and project definition.")

        def _path_row(self, field: QLineEdit, choose_callback: object) -> QWidget:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            button = QPushButton("Browse…")
            button.clicked.connect(choose_callback)
            layout.addWidget(field, 1)
            layout.addWidget(button)
            return row

        def _choose_installation(self) -> None:
            directory = QFileDialog.getExistingDirectory(
                self, "Select Perple_X installation folder", self.installation_edit.text()
            )
            if directory:
                self.installation_edit.setText(directory)
                self.build_editor.refresh_files()

        def _use_created_project(self, project_file: Path) -> None:
            self.project_edit.setText(str(project_file))
            self.tabs.setCurrentIndex(1)
            self.statusBar().showMessage(
                f"Created {project_file.name}. Run it when the BUILD selections are ready."
            )

        def _choose_project(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "Select Perple_X project definition",
                str(Path(self.project_edit.text()).parent),
                "Perple_X project (*.dat)",
            )
            if filename:
                self.project_edit.setText(filename)

        def _run_convex(self) -> None:
            if self._process is not None:
                return
            try:
                installation = PerpleXInstallation.discover(self.installation_edit.text())
                ghostscript = find_ghostscript()
                if ghostscript is None:
                    raise ValueError(
                        "Ghostscript was not found. Install it to generate PNG figure previews."
                    )
                run_directory = (
                    Path(gettempdir())
                    / "PerpleXStudio"
                    / "runs"
                    / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                )
                self._staged_project = stage_project(
                    self.project_edit.text(), run_directory, installation
                )
            except ValueError as error:
                QMessageBox.warning(self, "Cannot start calculation", str(error))
                return

            self._settings.setValue("installation_path", self.installation_edit.text())
            self._settings.setValue("project_path", self.project_edit.text())
            self._installation = installation
            self._ghostscript = ghostscript
            self.log.clear()
            self.save_figure_button.setEnabled(False)
            self._figure_pixmap = None
            self._zoom_factor = 1.0
            for button in (self.zoom_out_button, self.zoom_in_button, self.reset_zoom_button):
                button.setEnabled(False)
            self.figure.clear()
            self.figure.setText("Calculation is running…")
            self._append_log(f"Run directory: {self._staged_project.working_directory}\n")
            self.run_button.setEnabled(False)
            try:
                project_type = calculation_type(self._staged_project.project_file)
            except ValueError as error:
                self._finish_with_error(str(error))
                return
            if project_type == 1:
                self._start_stage("CONVEX")
            elif project_type == 5:
                self._start_stage("VERTEX")
            else:
                self._finish_with_error(
                    f"Calculation type {project_type} is not automated yet. "
                    "Studio currently runs types 1 (CONVEX) and 5 (VERTEX/PSSECT)."
                )

        def _start_stage(self, stage: str) -> None:
            if self._staged_project is None or self._installation is None:
                return
            self._stage = stage
            self._stage_had_perplex_error = False
            program: Path
            arguments: list[str] = []
            input_text = ""
            if stage == "CONVEX":
                program = self._installation.executables["convex.exe"]
                input_text = f"{self._staged_project.project_name}\n"
            elif stage == "VERTEX":
                program = self._installation.executables["vertex.exe"]
                input_text = f"{self._staged_project.project_name}\n"
            elif stage == "PSVDRAW":
                program = self._installation.executables["psvdraw.exe"]
                input_text = f"{self._staged_project.project_name}\nn\n"
            elif stage == "PSSECT":
                program = self._installation.executables["pssect.exe"]
                input_text = f"{self._staged_project.project_name}\nn\n"
            else:
                if self._ghostscript is None:
                    self._finish_with_error("Ghostscript was not configured.")
                    return
                program = self._ghostscript
                output = self._staged_project.working_directory / f"{self._staged_project.project_name}.png"
                postscript = self._staged_project.working_directory / f"{self._staged_project.project_name}.ps"
                arguments = [
                    "-dSAFER",
                    "-dBATCH",
                    "-dNOPAUSE",
                    "-sDEVICE=pngalpha",
                    "-r180",
                    f"-sOutputFile={output}",
                    str(postscript),
                ]

            self._append_log(f"\n--- {stage} ---\n")
            self.statusBar().showMessage(f"{stage} is running…")

            self._process = QProcess(self)
            self._process.setWorkingDirectory(str(self._staged_project.working_directory))
            self._process.readyReadStandardOutput.connect(self._read_stdout)
            self._process.readyReadStandardError.connect(self._read_stderr)
            self._process.finished.connect(self._process_finished)
            self._process.errorOccurred.connect(self._process_error)
            if input_text:
                self._process.started.connect(lambda: self._send_stage_input(input_text))
            self._process.start(str(program), arguments)

        def _send_stage_input(self, input_text: str) -> None:
            if self._process is not None:
                self._process.write(input_text.encode())
                self._process.closeWriteChannel()

        def _read_stdout(self) -> None:
            if self._process is not None:
                output = bytes(self._process.readAllStandardOutput()).decode(errors="replace")
                if "**error" in output.casefold():
                    self._stage_had_perplex_error = True
                self._append_log(output)

        def _read_stderr(self) -> None:
            if self._process is not None:
                output = bytes(self._process.readAllStandardError()).decode(errors="replace")
                if "**error" in output.casefold():
                    self._stage_had_perplex_error = True
                self._append_log(output)

        def _process_finished(self, exit_code: int, _exit_status: object) -> None:
            self._read_stdout()
            self._read_stderr()
            stage = self._stage
            project = self._staged_project
            self._process = None
            if exit_code != 0 or self._stage_had_perplex_error or project is None:
                self._finish_with_error(f"{stage} finished with exit code {exit_code}.")
                return
            if stage == "CONVEX":
                self._start_stage("PSVDRAW")
            elif stage == "VERTEX":
                self._start_stage("PSSECT")
            elif stage == "PSVDRAW":
                self._start_stage("Ghostscript")
            elif stage == "PSSECT":
                self._start_stage("Ghostscript")
            else:
                result = project.working_directory / f"{project.project_name}.png"
                pixmap = QPixmap(str(result))
                if pixmap.isNull():
                    self._finish_with_error(f"Ghostscript did not create a readable PNG: {result}")
                    return
                self._figure_pixmap = pixmap
                self._zoom_factor = 1.0
                self._apply_zoom()
                message = f"Finished. Preview: {result}"
                self._append_log(f"\n{message}\n")
                self.statusBar().showMessage(message)
                self.run_button.setEnabled(True)
                self.save_figure_button.setEnabled(True)
                for button in (self.zoom_out_button, self.zoom_in_button, self.reset_zoom_button):
                    button.setEnabled(True)

        def _process_error(self, _error: object) -> None:
            if self._process is None:
                return
            message = f"Could not start {self._stage}: {self._process.errorString()}"
            self._process = None
            self._finish_with_error(message)

        def _finish_with_error(self, message: str) -> None:
            self._append_log(f"\n{message}\n")
            self.figure.setText(message)
            self.run_button.setEnabled(True)
            self.statusBar().showMessage(message)

        def _save_figure_as(self) -> None:
            if self._staged_project is None:
                return
            project_name = self._staged_project.project_name
            filename, selected_filter = QFileDialog.getSaveFileName(
                self,
                "Save Perple_X figure",
                str(Path.home() / f"{project_name}.png"),
                "PNG image (*.png);;PostScript figure (*.ps)",
            )
            if not filename:
                return

            source = self._staged_project.working_directory / f"{project_name}.png"
            suffix = ".png"
            if selected_filter.startswith("PostScript"):
                source = self._staged_project.working_directory / f"{project_name}.ps"
                suffix = ".ps"
            destination = Path(filename)
            if not destination.suffix:
                destination = destination.with_suffix(suffix)
            try:
                copy2(source, destination)
            except OSError as error:
                QMessageBox.warning(self, "Could not save figure", str(error))
                return
            self.statusBar().showMessage(f"Figure saved: {destination}")
            self._append_log(f"Figure saved: {destination}\n")

        def _change_zoom(self, multiplier: float) -> None:
            if self._figure_pixmap is None:
                return
            self._zoom_factor = max(0.2, min(5.0, self._zoom_factor * multiplier))
            self._apply_zoom()

        def _reset_zoom(self) -> None:
            if self._figure_pixmap is None:
                return
            self._zoom_factor = 1.0
            self._apply_zoom()

        def _apply_zoom(self) -> None:
            if self._figure_pixmap is None:
                return
            scaled = self._figure_pixmap.scaled(
                round(self._figure_pixmap.width() * self._zoom_factor),
                round(self._figure_pixmap.height() * self._zoom_factor),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.figure.setPixmap(scaled)
            self.figure.resize(scaled.size())
            self.statusBar().showMessage(f"Figure zoom: {self._zoom_factor:.0%}")

        def _append_log(self, text: str) -> None:
            self.log.appendPlainText(text.rstrip("\n"))
            self.log.ensureCursorVisible()

    application = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
