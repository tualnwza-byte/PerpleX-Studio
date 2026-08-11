"""PySide6 desktop application entry point."""

from __future__ import annotations

import json
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
from perplex_studio.shortcut import create_desktop_shortcut


def studio_icon_path() -> Path:
    """Return the bundled Windows icon when it is available."""
    return Path(__file__).with_name("assets") / "PerpleX_Studio.ico"


def main() -> None:
    """Start the PerpleX Studio desktop application."""
    try:
        from PySide6.QtCore import QEvent, QLocale, QProcess, QSettings, Qt
        from PySide6.QtGui import QIcon, QPixmap
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

    class FigurePreviewScrollArea(QScrollArea):
        """A zoomed figure viewport that supports Space + drag panning."""

        def __init__(self) -> None:
            super().__init__()
            self._space_pressed = False
            self._panning = False
            self._last_pan_position = None
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            QApplication.instance().installEventFilter(self)

        def setWidget(self, widget: QWidget) -> None:  # type: ignore[override]
            super().setWidget(widget)
            widget.installEventFilter(self)

        def eventFilter(self, watched: object, event: object) -> bool:  # type: ignore[override]
            event_type = event.type()
            if event_type == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space:
                if self.underMouse() or (self.widget() is not None and self.widget().underMouse()):
                    self._space_pressed = True
                    self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
                    return True
            elif event_type == QEvent.Type.KeyRelease and event.key() == Qt.Key.Key_Space:
                if self._space_pressed:
                    self._space_pressed = False
                    self._panning = False
                    self.viewport().unsetCursor()
                    return True

            if watched is self.widget():
                if (
                    event_type == QEvent.Type.MouseButtonPress
                    and self._space_pressed
                    and event.button() == Qt.MouseButton.LeftButton
                ):
                    self._panning = True
                    self._last_pan_position = event.globalPosition().toPoint()
                    self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                    return True
                if event_type == QEvent.Type.MouseMove and self._panning:
                    position = event.globalPosition().toPoint()
                    delta = position - self._last_pan_position
                    self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
                    self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
                    self._last_pan_position = position
                    return True
                if event_type == QEvent.Type.MouseButtonRelease and self._panning:
                    self._panning = False
                    self._last_pan_position = None
                    self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
                    return True
            return super().eventFilter(watched, event)

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
            self._settings = QSettings("PerpleX Studio", "PerpleX Studio")
            self._defaults_loaded = False
            self.database: object | None = None
            self.project_name = QLineEdit("my_project")
            default_directory = self._settings.value(
                "default_project_directory", str(Path.cwd()), type=str
            )
            self.project_directory = QLineEdit(default_directory)
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
                "Check one or more phases to exclude them. Selecting a phase automatically "
                "enables exclusion for the generated Perple_X project."
            )
            self.phase_exclusion_help.setWordWrap(True)
            self.solution_models = QCheckBox("Include solution models")
            self.title = QLineEdit()
            self.save_button = QPushButton("Save BUILD setup…")
            self.save_button.clicked.connect(self._save_setup)
            self.create_dat_button = QPushButton("Create .dat Project")
            self.create_dat_button.clicked.connect(self._create_dat)
            self.restore_defaults_button = QPushButton("Restore Defaults")
            self.restore_defaults_button.setToolTip(
                "Reset Build Input settings to Studio defaults. The Perple_X installation and database stay selected."
            )
            self.restore_defaults_button.clicked.connect(self._restore_defaults)
            self.set_default_button = QPushButton("Set as Default")
            self.set_default_button.setToolTip(
                "Save the current BUILD choices as the starting template for future sessions."
            )
            self.set_default_button.clicked.connect(self._save_as_default)

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
            identity.addRow("Projects folder", directory_row)
            project_folder_help = QLabel(
                "Studio creates a separate folder named after the project inside this location."
            )
            project_folder_help.setWordWrap(True)
            identity.addRow("", project_folder_help)
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
            actions.addWidget(self.restore_defaults_button)
            actions.addWidget(self.set_default_button)
            actions.addStretch()
            root.addLayout(actions)
            root.addStretch()

            self.saturated_fluid.toggled.connect(self._set_fluid_enabled)
            self.database_menu.currentIndexChanged.connect(lambda _index: self._load_database())
            self.components.itemChanged.connect(lambda _item: self._sync_component_amounts())
            self.phase_exclusions.itemChanged.connect(self._phase_exclusion_changed)
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
            self._apply_saved_defaults()

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
                    category = "derived" if phase.derived else "phase"
                    component_text = " + ".join(phase.components) or "components unresolved"
                    item = QListWidgetItem(
                        f"{phase.name}  —  {component_text}  ({category})"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, phase.name)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked if phase.name in checked else Qt.CheckState.Unchecked
                    )
                    self.phase_exclusions.addItem(item)

        def _phase_exclusion_changed(self, item: QListWidgetItem) -> None:
            if item.checkState() == Qt.CheckState.Checked:
                self.exclude_phases.setChecked(True)

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
                self, "Select projects folder", self.project_directory.text()
            )
            if directory:
                self.project_directory.setText(directory)

        def _restore_defaults(self) -> None:
            """Return editable BUILD fields to safe Studio starting values."""
            answer = QMessageBox.question(
                self,
                "Restore BUILD defaults?",
                "Reset the current Build Input settings? The Perple_X installation and selected database will remain available.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.project_name.setText("my_project")
            self.project_directory.setText(str(Path.cwd()))
            self.transform.setChecked(False)
            self.component_mode.setCurrentIndex(1)
            self.saturated_fluid.setChecked(False)
            self.h2o.setChecked(False)
            self.co2.setChecked(False)
            self.saturated_component_constraint.setChecked(False)
            self.independent_potentials.setChecked(False)
            self.fluid_eos.setCurrentIndex(0)
            self.geothermal_gradient.setChecked(False)
            self.diagram_type.setCurrentIndex(2)
            self.print_file.setChecked(False)
            self.exclude_phases.setChecked(False)
            self.solution_models.setChecked(False)
            self.title.clear()
            option_index = self.option_menu.findText("perplex_option.dat")
            if option_index >= 0:
                self.option_menu.setCurrentIndex(option_index)
            for widget in (self.components, self.saturated_components, self.phase_exclusions):
                for index in range(widget.count()):
                    widget.item(index).setCheckState(Qt.CheckState.Unchecked)
            self._component_amounts.clear()
            self._sync_component_amounts()
            self.x_minimum.setValue(0.0)
            self.x_maximum.setValue(0.0)
            self.y_minimum.setValue(0.0)
            self.y_maximum.setValue(0.0)
            self.section_value.setValue(0.0)
            if self.x_variable.findText("T(K)") >= 0:
                self.x_variable.setCurrentText("T(K)")
            if self.y_variable.findText("P(bar)") >= 0:
                self.y_variable.setCurrentText("P(bar)")

        @staticmethod
        def _set_checked(widget: QListWidget, names: tuple[str, ...] | list[str]) -> None:
            selected = set(names)
            for index in range(widget.count()):
                item = widget.item(index)
                item.setCheckState(
                    Qt.CheckState.Checked if item.text() in selected else Qt.CheckState.Unchecked
                )

        def _set_phase_exclusions(self, names: tuple[str, ...] | list[str]) -> None:
            selected = set(names)
            for index in range(self.phase_exclusions.count()):
                item = self.phase_exclusions.item(index)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if item.data(Qt.ItemDataRole.UserRole) in selected
                    else Qt.CheckState.Unchecked
                )

        def _save_as_default(self) -> None:
            setup = self._collect_setup()
            if setup is None:
                return
            self._settings.setValue("build_default_setup", json.dumps(setup.__dict__))
            QMessageBox.information(
                self,
                "Default template saved",
                "These BUILD choices will be restored when PerpleX Studio opens. "
                "Project name and project folder remain user-specific.",
            )

        def _apply_saved_defaults(self) -> None:
            if self._defaults_loaded:
                return
            self._defaults_loaded = True
            stored = self._settings.value("build_default_setup", "", type=str)
            if not stored:
                return
            try:
                defaults = json.loads(stored)
            except (TypeError, json.JSONDecodeError):
                return
            database_index = self.database_menu.findText(defaults.get("database_file", ""))
            if database_index >= 0:
                self.database_menu.setCurrentIndex(database_index)
            option_index = self.option_menu.findText(defaults.get("option_file", ""))
            if option_index >= 0:
                self.option_menu.setCurrentIndex(option_index)
            mode_index = self.component_mode.findText(defaults.get("component_mode", ""))
            if mode_index >= 0:
                self.component_mode.setCurrentIndex(mode_index)
            self.saturated_fluid.setChecked(bool(defaults.get("saturated_fluid", False)))
            self.h2o.setChecked("H2O" in defaults.get("saturated_components", ()))
            self.co2.setChecked("CO2" in defaults.get("saturated_components", ()))
            self.saturated_component_constraint.setChecked(
                bool(defaults.get("saturated_component_constraint", False))
            )
            self._set_checked(
                self.saturated_components,
                tuple(name for name in defaults.get("saturated_components", ()) if name not in {"H2O", "CO2"}),
            )
            self._component_amounts = {
                name: amount for name, amount in defaults.get("component_amounts", ())
            }
            self._set_checked(self.components, tuple(defaults.get("thermodynamic_components", ())))
            self.independent_potentials.setChecked(bool(defaults.get("independent_potentials", False)))
            eos_index = self.fluid_eos.findText(defaults.get("fluid_eos", ""))
            if eos_index >= 0:
                self.fluid_eos.setCurrentIndex(eos_index)
            self.geothermal_gradient.setChecked(bool(defaults.get("geothermal_gradient", False)))
            diagram_index = self.diagram_type.findText(defaults.get("diagram_type", ""))
            if diagram_index >= 0:
                self.diagram_type.setCurrentIndex(diagram_index)
            for widget, key in (
                (self.x_variable, "x_variable"),
                (self.y_variable, "y_variable"),
                (self.section_variable, "section_variable"),
            ):
                index = widget.findText(defaults.get(key, ""))
                if index >= 0:
                    widget.setCurrentIndex(index)
            self.x_minimum.setValue(float(defaults.get("x_minimum", 0.0)))
            self.x_maximum.setValue(float(defaults.get("x_maximum", 0.0)))
            self.y_minimum.setValue(float(defaults.get("y_minimum", 0.0)))
            self.y_maximum.setValue(float(defaults.get("y_maximum", 0.0)))
            self.section_value.setValue(float(defaults.get("section_value", 0.0)))
            self.print_file.setChecked(bool(defaults.get("print_file", False)))
            self.exclude_phases.setChecked(bool(defaults.get("exclude_phases", False)))
            self.solution_models.setChecked(bool(defaults.get("solution_models", False)))
            self._sync_component_amounts()
            self._set_phase_exclusions(tuple(defaults.get("excluded_phase_names", ())))

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
            root = Path(self.project_directory.text()).expanduser()
            if not root.is_dir():
                QMessageBox.warning(self, "Invalid projects folder", "Select an existing projects folder.")
                return
            project_folder = root / setup.project_name
            project_folder.mkdir(parents=True, exist_ok=True)
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save Studio BUILD setup",
                str(project_folder / f"{setup.project_name}.perplex-studio.json"),
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
            root = Path(self.project_directory.text()).expanduser()
            if not root.is_dir():
                QMessageBox.warning(self, "Invalid projects folder", "Select an existing projects folder.")
                return
            folder = root / setup.project_name
            if folder.exists() and any(folder.iterdir()) and not (folder / f"{setup.project_name}.dat").exists():
                answer = QMessageBox.question(
                    self,
                    "Use existing project folder?",
                    f"{folder.name} already contains files. Continue and keep them?",
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            folder.mkdir(parents=True, exist_ok=True)
            output = folder / f"{setup.project_name}.dat"
            if output.exists():
                answer = QMessageBox.question(
                    self, "Replace project?", f"{output.name} already exists. Replace it?"
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            try:
                created = write_convex_section_dat(setup, database, output)
                save_build_setup(setup, folder / f"{setup.project_name}.perplex-studio.json")
            except ValueError as error:
                QMessageBox.warning(self, "Cannot create .dat project", str(error))
                return
            QMessageBox.information(
                self,
                "Perple_X project created",
                f"Project folder: {folder}\n\nCreated: {created.name}\nSaved: {setup.project_name}.perplex-studio.json",
            )
            if callable(self.project_created):
                self.project_created(created)

    class SettingsPage(QWidget):
        """Application-wide preferences, kept separate from BUILD inputs."""

        def __init__(self, apply_callback: object, create_shortcut_callback: object) -> None:
            super().__init__()
            self._settings = QSettings("PerpleX Studio", "PerpleX Studio")
            self._apply_callback = apply_callback
            self._create_shortcut_callback = create_shortcut_callback

            self.installation_edit = QLineEdit(
                self._settings.value("installation_path", "", type=str)
            )
            self.project_folder_edit = QLineEdit(
                self._settings.value("default_project_directory", str(Path.cwd()), type=str)
            )
            configured_ghostscript = self._settings.value("ghostscript_path", "", type=str)
            detected_ghostscript = find_ghostscript()
            self.ghostscript_edit = QLineEdit(
                configured_ghostscript or (str(detected_ghostscript) if detected_ghostscript else "")
            )
            self.shortcut_option = QCheckBox("Enable the optional desktop shortcut")
            self.shortcut_option.setChecked(
                self._settings.value("desktop_shortcut_option", True, type=bool)
            )
            self.shortcut_button = QPushButton("Create Desktop Shortcut")
            self.shortcut_button.setToolTip(
                "Create or update a PerpleX Studio shortcut on the current Windows desktop."
            )
            self.shortcut_button.setEnabled(self.shortcut_option.isChecked())
            self.shortcut_option.toggled.connect(self.shortcut_button.setEnabled)
            self.shortcut_option.toggled.connect(
                lambda checked: self._settings.setValue("desktop_shortcut_option", checked)
            )
            self.shortcut_button.clicked.connect(self._create_shortcut)

            self.save_button = QPushButton("Save Settings")
            self.save_button.clicked.connect(self._save)
            self.reset_button = QPushButton("Restore Studio Defaults")
            self.reset_button.setToolTip(
                "Reset Studio preferences and saved BUILD templates. Project files are not changed."
            )
            self.reset_button.clicked.connect(self._reset)

            root = QVBoxLayout(self)
            header = QLabel(
                "Application preferences. Scientific choices such as bulk composition, "
                "solution models, and P–T limits remain in Build Input."
            )
            header.setWordWrap(True)
            root.addWidget(header)

            paths = QFormLayout()
            paths.addRow("Default Perple_X installation", self._path_row(
                self.installation_edit, "Select Perple_X installation", True
            ))
            paths.addRow("Default projects folder", self._path_row(
                self.project_folder_edit, "Select default projects folder", True
            ))
            paths.addRow("Ghostscript executable", self._path_row(
                self.ghostscript_edit, "Select gswin64c.exe", False
            ))
            root.addWidget(self._box("Paths and tools", paths))

            shortcut_layout = QVBoxLayout()
            shortcut_layout.addWidget(self.shortcut_option)
            shortcut_layout.addWidget(QLabel(
                "A shortcut is never required. It opens Studio using the same Python "
                "environment used to create it."
            ))
            shortcut_layout.addWidget(self.shortcut_button)
            root.addWidget(self._box("Desktop shortcut", shortcut_layout))

            about = QLabel(
                '<b>PerpleX Studio</b><br>'
                'Experimental graphical interface for Perple_X.<br><br>'
                'Developed with assistance from AI coding tools. It does not use AI to '
                'perform thermodynamic calculations or interpret scientific results.<br><br>'
                '<a href="https://www.perplex.ethz.ch/">Perple_X official website</a> '
                '· <a href="https://github.com/tualnwza-byte/PerpleX-Studio">Studio source code</a>'
            )
            about.setWordWrap(True)
            about.setOpenExternalLinks(True)
            root.addWidget(self._box("About", about))

            actions = QHBoxLayout()
            actions.addWidget(self.save_button)
            actions.addWidget(self.reset_button)
            actions.addStretch()
            root.addLayout(actions)
            root.addStretch()

        def _box(self, title: str, content: object) -> QGroupBox:
            box = QGroupBox(title)
            if isinstance(content, QFormLayout):
                box.setLayout(content)
            else:
                layout = QVBoxLayout(box)
                if isinstance(content, QWidget):
                    layout.addWidget(content)
                else:
                    layout.addLayout(content)
            return box

        def _path_row(self, field: QLineEdit, title: str, directory: bool) -> QWidget:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            button = QPushButton("Browse…")

            def choose() -> None:
                if directory:
                    value = QFileDialog.getExistingDirectory(self, title, field.text())
                else:
                    value, _ = QFileDialog.getOpenFileName(self, title, field.text(), "Executable (*.exe)")
                if value:
                    field.setText(value)

            button.clicked.connect(choose)
            layout.addWidget(field, 1)
            layout.addWidget(button)
            return row

        def _save(self) -> None:
            project_folder = Path(self.project_folder_edit.text()).expanduser()
            if not project_folder.is_dir():
                QMessageBox.warning(self, "Invalid projects folder", "Choose an existing default projects folder.")
                return
            ghostscript_value = self.ghostscript_edit.text().strip()
            if ghostscript_value and not Path(ghostscript_value).is_file():
                QMessageBox.warning(self, "Invalid Ghostscript", "Choose the gswin64c.exe executable or clear this field.")
                return
            self._settings.setValue("installation_path", self.installation_edit.text().strip())
            self._settings.setValue("default_project_directory", str(project_folder))
            self._settings.setValue("ghostscript_path", ghostscript_value)
            if callable(self._apply_callback):
                self._apply_callback(self.installation_edit.text().strip(), str(project_folder))
            QMessageBox.information(self, "Settings saved", "Studio preferences were saved.")

        def _create_shortcut(self) -> None:
            if callable(self._create_shortcut_callback):
                self._create_shortcut_callback()

        def _reset(self) -> None:
            answer = QMessageBox.question(
                self,
                "Restore Studio Defaults?",
                "This resets Studio preferences and saved BUILD templates. It does not delete "
                "Perple_X installations, project files, or results.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._settings.clear()
            self.installation_edit.clear()
            self.project_folder_edit.setText(str(Path.cwd()))
            self.ghostscript_edit.setText(str(find_ghostscript() or ""))
            self.shortcut_option.setChecked(True)
            if callable(self._apply_callback):
                self._apply_callback("", str(Path.cwd()))
            QMessageBox.information(self, "Studio defaults restored", "Restart Studio to reload every saved template.")

    class MainWindow(QMainWindow):
        """Interface for running staged Perple_X Convex-Hull and grid projects."""

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("PerpleX Studio")
            if studio_icon_path().is_file():
                self.setWindowIcon(QIcon(str(studio_icon_path())))
            self.resize(1080, 720)
            self.setStyleSheet(
                """
                QMainWindow { background: #ffffff; color: #1f1b2d; }
                QWidget {
                    background: #ffffff; color: #1f1b2d; font-family: "Segoe UI";
                    font-size: 13px;
                }
                QLabel { color: #45405a; }
                QTabWidget::pane {
                    background: #ffffff; border: 1px solid #ddd6fe; border-radius: 10px;
                    top: -1px;
                }
                QTabBar::tab {
                    background: #f5f3ff; border: 1px solid #ddd6fe; border-bottom: none;
                    border-top-left-radius: 8px; border-top-right-radius: 8px;
                    color: #5b5680; padding: 9px 18px; margin-right: 4px; font-weight: 600;
                }
                QTabBar::tab:hover { background: #ede9fe; color: #5b21b6; }
                QTabBar::tab:selected {
                    background: #ffffff; color: #5b21b6; border-color: #a78bfa;
                }
                QGroupBox {
                    background: #ffffff; border: 1px solid #ddd6fe; border-radius: 10px;
                    margin-top: 16px; padding: 16px 14px 14px 14px; font-weight: 700;
                    color: #3b1b75;
                }
                QGroupBox::title {
                    subcontrol-origin: margin; left: 14px; padding: 0 7px;
                    color: #5b21b6; background: #ffffff; font-size: 14px;
                }
                QLineEdit, QComboBox, QDoubleSpinBox, QListWidget, QPlainTextEdit, QTableWidget {
                    background: #ffffff; border: 1px solid #c4b5fd; border-radius: 6px;
                    color: #27213d; min-height: 28px; padding: 3px 8px;
                }
                QLineEdit:hover, QComboBox:hover, QDoubleSpinBox:hover, QListWidget:hover, QTableWidget:hover {
                    border-color: #a78bfa;
                }
                QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QListWidget:focus, QTableWidget:focus {
                    border: 2px solid #7c3aed; background: #fdfcff;
                }
                QComboBox::drop-down { border-left: 1px solid #ddd6fe; width: 28px; }
                QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #c4b5fd; }
                QListWidget::item { padding: 6px; border-radius: 4px; }
                QListWidget::item:hover { background: #f5f3ff; }
                QListWidget::item:selected { background: #ede9fe; color: #3b1b75; }
                QHeaderView::section {
                    background: #f5f3ff; color: #5b21b6; border: none;
                    border-bottom: 1px solid #ddd6fe; padding: 7px; font-weight: 700;
                }
                QCheckBox {
                    background: #fbfaff; border: 1px solid #ddd6fe; border-radius: 6px;
                    spacing: 8px; padding: 6px 9px;
                }
                QCheckBox:hover { background: #f5f3ff; border-color: #a78bfa; }
                QCheckBox:checked { background: #f0edff; border-color: #7c3aed; font-weight: 600; }
                QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #8b7ab8; background: #ffffff; }
                QCheckBox::indicator:checked { background: #6d28d9; border-color: #5b21b6; }
                QListWidget::indicator { width: 16px; height: 16px; border: 1px solid #8b7ab8; background: #ffffff; }
                QListWidget::indicator:checked { background: #6d28d9; border-color: #5b21b6; }
                QPushButton {
                    background: #6d28d9; color: #ffffff; border: 1px solid #5b21b6;
                    border-radius: 6px; padding: 8px 14px; font-weight: 700; min-height: 20px;
                }
                QPushButton:hover { background: #5b21b6; border-color: #4c1d95; }
                QPushButton:pressed { background: #4c1d95; }
                QPushButton:disabled { background: #ede9fe; color: #8b7ab8; border-color: #ddd6fe; }
                QScrollArea, QScrollArea::viewport { background: #ffffff; border: none; }
                QScrollBar:vertical { background: #f5f3ff; width: 11px; margin: 2px; border-radius: 5px; }
                QScrollBar::handle:vertical { background: #c4b5fd; min-height: 32px; border-radius: 5px; }
                QScrollBar::handle:vertical:hover { background: #a78bfa; }
                QScrollBar:horizontal { background: #f5f3ff; height: 11px; margin: 2px; border-radius: 5px; }
                QScrollBar::handle:horizontal { background: #c4b5fd; min-width: 32px; border-radius: 5px; }
                QScrollBar::handle:horizontal:hover { background: #a78bfa; }
                QStatusBar { background: #2e1065; color: #ffffff; font-weight: 500; }
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
            self.figure_scroll = FigurePreviewScrollArea()
            self.figure_scroll.setStyleSheet("QScrollArea { background: white; border: 1px solid #d9e2ec; }")
            self.figure_scroll.setBackgroundRole(self.figure.backgroundRole())
            self.figure_scroll.setWidget(self.figure)
            self.figure_scroll.setWidgetResizable(False)
            self.figure_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self.build_editor = BuildEditor(self.installation_edit, self._use_created_project)
            self.build_editor.refresh_files()
            self.settings_page = SettingsPage(self._apply_settings, self._create_desktop_shortcut)

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
            figure_header.addWidget(QLabel("Figure preview — hold Space and drag to pan"))
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
            self.tabs.addTab(self.settings_page, "Settings")
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

        def _apply_settings(self, installation_path: str, project_folder: str) -> None:
            self.installation_edit.setText(installation_path)
            self.build_editor.project_directory.setText(project_folder)
            self.build_editor.refresh_files()

        def _choose_project(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "Select Perple_X project definition",
                str(Path(self.project_edit.text()).parent),
                "Perple_X project (*.dat)",
            )
            if filename:
                self.project_edit.setText(filename)

        def _create_desktop_shortcut(self) -> None:
            try:
                shortcut = create_desktop_shortcut(
                    sys.executable, Path.cwd(), studio_icon_path()
                )
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Could not create shortcut", str(error))
                return
            QMessageBox.information(
                self,
                "Desktop shortcut created",
                f"Created: {shortcut}\n\nYou can now open PerpleX Studio from this shortcut.",
            )

        def _run_convex(self) -> None:
            if self._process is not None:
                return
            try:
                installation = PerpleXInstallation.discover(self.installation_edit.text())
                configured_ghostscript = Path(
                    self._settings.value("ghostscript_path", "", type=str)
                )
                ghostscript = configured_ghostscript if configured_ghostscript.is_file() else find_ghostscript()
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
    if studio_icon_path().is_file():
        application.setWindowIcon(QIcon(str(studio_icon_path())))
    window = MainWindow()
    window.show()
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
