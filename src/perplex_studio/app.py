"""PySide6 desktop application entry point."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from shutil import copy2, which
from tempfile import gettempdir

from perplex_studio.build_config import (
    BuildSetup,
    phase_full_name,
    read_database,
    save_build_setup,
    write_convex_section_dat,
)
from perplex_studio.perplex_installation import PerpleXInstallation
from perplex_studio.runner import (
    StagedProject,
    calculation_type,
    stage_project,
)
from perplex_studio.shortcut import create_desktop_shortcut
from perplex_studio.vector_figure import convert_postscript_to_svg


def studio_icon_path() -> Path:
    """Return the bundled Windows icon when it is available."""
    return Path(__file__).with_name("assets") / "PerpleX_Studio.ico"


def main() -> None:
    """Start the PerpleX Studio desktop application."""
    try:
        from PySide6.QtCore import QEvent, QLocale, QProcess, QSettings, Qt, QRectF, QSize
        from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
        from PySide6.QtSvg import QSvgGenerator, QSvgRenderer
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
            QHeaderView,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QInputDialog,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QPlainTextEdit,
            QTableWidget,
            QTableWidgetItem,
            QScrollArea,
            QSpinBox,
            QSplitter,
            QStatusBar,
            QTabWidget,
            QToolButton,
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
            self._annotation_click_callback: object | None = None
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            QApplication.instance().installEventFilter(self)

        def setWidget(self, widget: QWidget) -> None:  # type: ignore[override]
            super().setWidget(widget)
            widget.installEventFilter(self)

        def set_annotation_click_callback(self, callback: object) -> None:
            self._annotation_click_callback = callback

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
                    and not self._space_pressed
                    and event.button() == Qt.MouseButton.LeftButton
                    and callable(self._annotation_click_callback)
                ):
                    if self._annotation_click_callback(event.position().toPoint()):
                        return True
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

    class VectorFigureWidget(QWidget):
        """Paint the Perple_X SVG directly; never flatten the working preview to pixels."""

        def __init__(self) -> None:
            super().__init__()
            self._renderer = QSvgRenderer(self)
            self._overlay_callback: object | None = None
            self._reaction_equations: list[tuple[int, str]] = []
            self._legend_lines: list[tuple[str, str]] = []
            self._message = "The generated vector diagram will appear here."
            self.setMinimumSize(1, 1)
            self.setStyleSheet("background: white;")

        @property
        def natural_height(self) -> int:
            return 800 if not self._legend_lines else 902 + 20 * (len(self._legend_lines) - 1)

        def set_reaction_equations(self, equations: list[tuple[int, str]]) -> None:
            """Show the equations Perple_X used for numbered univariant lines."""
            self._reaction_equations = equations
            self._legend_lines = []
            font = QFont("Segoe UI", 12)
            metrics = QFontMetrics(font)
            available = 720
            for number, equation in equations:
                words = equation.split()
                lines: list[str] = []
                current = ""
                for word in words:
                    candidate = f"{current} {word}".strip()
                    if current and metrics.horizontalAdvance(candidate) > available:
                        lines.append(current)
                        current = word
                    else:
                        current = candidate
                if current:
                    lines.append(current)
                for index, line in enumerate(lines or [equation]):
                    self._legend_lines.append((str(number) if index == 0 else "", line))
            self.updateGeometry()
            self.update()

        def set_svg_file(self, filename: str | Path) -> bool:
            loaded = self._renderer.load(str(filename))
            self._message = "" if loaded else f"Could not open vector diagram: {filename}"
            self.update()
            return loaded

        def set_overlay_callback(self, callback: object) -> None:
            self._overlay_callback = callback

        def setText(self, text: str) -> None:
            self._message = text
            self.update()

        def clear(self) -> None:
            self._renderer = QSvgRenderer(self)
            self._message = ""
            self.update()

        def paintEvent(self, _event: object) -> None:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("white"))
            if self._renderer.isValid():
                self.render_vector(painter, QRectF(self.rect()))
            elif self._message:
                painter.setPen(QColor("#52606d"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            painter.end()

        def render_vector(self, painter: QPainter, target: QRectF) -> None:
            """Render source vectors and Studio overlays into any vector-capable painter."""
            if not self._renderer.isValid():
                return
            scale = target.width() / 800 if target.width() else 1
            diagram_target = QRectF(target.x(), target.y(), target.width(), 800 * scale)
            painter.fillRect(target, QColor("white"))
            self._renderer.render(painter, diagram_target)
            if callable(self._overlay_callback):
                painter.save()
                painter.translate(diagram_target.x(), diagram_target.y())
                painter.scale(scale, scale)
                self._overlay_callback(painter)
                painter.restore()
            if self._legend_lines:
                painter.save()
                painter.translate(target.x(), target.y())
                painter.scale(scale, scale)
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                painter.setPen(QPen(QColor("#334155"), 1))
                painter.drawLine(24, 816, 776, 816)
                heading_font = QFont("Segoe UI", 14)
                heading_font.setBold(True)
                painter.setFont(heading_font)
                painter.setPen(QColor("#2e1065"))
                painter.drawText(24, 840, "Univariant reactions (numbers match the diagram)")
                painter.setFont(QFont("Segoe UI", 10))
                painter.setPen(QColor("#64748b"))
                painter.drawText(24, 858, "Perple_X places the high-temperature assemblage to the right of =.")
                painter.setFont(QFont("Segoe UI", 11))
                painter.setPen(QColor("#1f2937"))
                y = 882
                for number, equation in self._legend_lines:
                    if number:
                        painter.setPen(QColor("#5b21b6"))
                        painter.drawText(28, y, 32, 18, Qt.AlignmentFlag.AlignLeft, number)
                    painter.setPen(QColor("#1f2937"))
                    painter.drawText(68, y, equation)
                    y += 20
                painter.restore()

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
            self.phase_filter = QLineEdit()
            self.phase_filter.setPlaceholderText(
                "Filter by abbreviation, phase name, formula, or make reaction…"
            )
            self.phase_exclusions = QTableWidget(0, 5)
            self.phase_exclusions.setHorizontalHeaderLabels(
                ("Exclude", "Abbreviation", "Full name", "Formula", "Make reaction")
            )
            self.phase_exclusions.verticalHeader().setVisible(False)
            self.phase_exclusions.setAlternatingRowColors(True)
            self.phase_exclusions.setMinimumHeight(220)
            self.phase_exclusions.setMaximumHeight(320)
            phase_header = self.phase_exclusions.horizontalHeader()
            phase_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            phase_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            phase_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            phase_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            phase_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
            self.select_all_phases_button = QPushButton("Exclude All Visible")
            self.clear_phase_exclusions_button = QPushButton("Clear Exclusions")
            self.select_all_phases_button.clicked.connect(self._exclude_all_visible_phases)
            self.clear_phase_exclusions_button.clicked.connect(self._clear_phase_exclusions)
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
            root.setContentsMargins(10, 10, 10, 10)
            header = QLabel(
                "BUILD configuration — set up a project, then create its Perple_X definition."
            )
            header.setObjectName("panelDescription")
            header.setWordWrap(True)
            root.addWidget(header)
            self.configuration_tabs = QTabWidget()
            root.addWidget(self.configuration_tabs, 1)

            project_page = QWidget()
            project_layout = QVBoxLayout(project_page)
            project_layout.setContentsMargins(8, 10, 8, 8)
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
            project_layout.addWidget(self._box("Project", identity))
            project_layout.addWidget(self.transform)
            project_layout.addStretch()
            self.configuration_tabs.addTab(project_page, "Project")

            composition_page = QWidget()
            composition_layout = QVBoxLayout(composition_page)
            composition_layout.setContentsMargins(8, 10, 8, 8)
            fluid = QGridLayout()
            fluid.addWidget(self.saturated_fluid, 0, 0, 1, 2)
            fluid.addWidget(self.h2o, 1, 0)
            fluid.addWidget(self.co2, 1, 1)
            fluid.addWidget(self.saturated_component_constraint, 2, 0, 1, 2)
            fluid.addWidget(QLabel("Select fewer than 6 saturated components"), 3, 0, 1, 2)
            fluid.addWidget(self.saturated_components, 4, 0, 1, 2)
            fluid.addWidget(QLabel("Saturated fluid EoS"), 5, 0)
            fluid.addWidget(self.fluid_eos, 5, 1)
            composition_layout.addWidget(self._box("Saturated fluid", fluid))

            composition_layout.addWidget(self.independent_potentials)
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
            composition_layout.addWidget(self._box("Thermodynamic components", components))
            composition_layout.addStretch()
            self.configuration_tabs.addTab(composition_page, "Components")

            diagram_page = QWidget()
            diagram_layout = QVBoxLayout(diagram_page)
            diagram_layout.setContentsMargins(8, 10, 8, 8)
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
            diagram_layout.addWidget(self._box("Independent variables", axes))
            diagram_layout.addStretch()
            self.configuration_tabs.addTab(diagram_page, "Diagram")

            phases_page = QWidget()
            phases_layout = QVBoxLayout(phases_page)
            phases_layout.setContentsMargins(8, 10, 8, 8)
            choices = QVBoxLayout()
            choices.addWidget(self.print_file)
            choices.addWidget(self.exclude_phases)
            choices.addWidget(self.phase_exclusion_help)
            choices.addWidget(self.phase_filter)
            phase_actions = QHBoxLayout()
            phase_actions.addWidget(self.select_all_phases_button)
            phase_actions.addWidget(self.clear_phase_exclusions_button)
            phase_actions.addStretch()
            choices.addLayout(phase_actions)
            choices.addWidget(self.phase_exclusions)
            choices.addWidget(self.solution_models)
            phases_layout.addWidget(self._box("Phases and models", choices))
            phases_layout.addStretch()
            self.configuration_tabs.addTab(phases_page, "Phases")
            actions = QHBoxLayout()
            actions.addWidget(self.create_dat_button)
            actions.addWidget(self.save_button)
            actions.addWidget(self.restore_defaults_button)
            actions.addWidget(self.set_default_button)
            actions.addStretch()
            root.addLayout(actions)

            self.saturated_fluid.toggled.connect(self._set_fluid_enabled)
            self.database_menu.currentIndexChanged.connect(lambda _index: self._load_database())
            self.components.itemChanged.connect(lambda _item: self._sync_component_amounts())
            self.phase_exclusions.itemChanged.connect(self._phase_exclusion_changed)
            self.phase_filter.textChanged.connect(self._filter_phase_rows)
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
            checked = set(self._checked_phase_exclusions())
            available = set(selected_components)
            if self.saturated_fluid.isChecked():
                available.update(self._checked(self.saturated_components))
                if self.h2o.isChecked():
                    available.add("H2O")
                if self.co2.isChecked():
                    available.add("CO2")
            self.phase_exclusions.blockSignals(True)
            self.phase_exclusions.setRowCount(0)
            if self.database is None:
                self.phase_exclusions.blockSignals(False)
                return
            for phase in self.database.pure_phases:
                # With no components selected, expose the full database list.
                # Once the user selects components, narrow it to compatible phases.
                if not available or set(phase.components).issubset(available):
                    row = self.phase_exclusions.rowCount()
                    self.phase_exclusions.insertRow(row)
                    exclude_item = QTableWidgetItem()
                    exclude_item.setData(Qt.ItemDataRole.UserRole, phase.name)
                    exclude_item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsUserCheckable
                    )
                    exclude_item.setCheckState(
                        Qt.CheckState.Checked if phase.name in checked else Qt.CheckState.Unchecked
                    )
                    self.phase_exclusions.setItem(row, 0, exclude_item)
                    self._set_phase_table_item(row, 1, phase.name)
                    self._set_phase_table_item(row, 2, phase_full_name(phase.name) or "—")
                    self._set_phase_table_item(row, 3, phase.formula or "—")
                    self._set_phase_table_item(row, 4, phase.make_reaction or "—")
            self.phase_exclusions.blockSignals(False)
            self._filter_phase_rows(self.phase_filter.text())

        def _set_phase_table_item(self, row: int, column: int, text: str) -> None:
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.phase_exclusions.setItem(row, column, item)

        def _phase_exclusion_changed(self, item: QTableWidgetItem) -> None:
            if item.column() == 0 and item.checkState() == Qt.CheckState.Checked:
                self.exclude_phases.setChecked(True)

        def _checked_phase_exclusions(self) -> tuple[str, ...]:
            return tuple(
                item.data(Qt.ItemDataRole.UserRole)
                for row in range(self.phase_exclusions.rowCount())
                if (item := self.phase_exclusions.item(row, 0)) is not None
                and item.checkState() == Qt.CheckState.Checked
            )

        def _filter_phase_rows(self, text: str) -> None:
            needle = text.casefold().strip()
            for row in range(self.phase_exclusions.rowCount()):
                row_text = " ".join(
                    self.phase_exclusions.item(row, column).text()
                    for column in range(1, self.phase_exclusions.columnCount())
                    if self.phase_exclusions.item(row, column) is not None
                ).casefold()
                self.phase_exclusions.setRowHidden(row, bool(needle) and needle not in row_text)

        def _exclude_all_visible_phases(self) -> None:
            self.phase_exclusions.blockSignals(True)
            for row in range(self.phase_exclusions.rowCount()):
                if not self.phase_exclusions.isRowHidden(row):
                    item = self.phase_exclusions.item(row, 0)
                    if item is not None:
                        item.setCheckState(Qt.CheckState.Checked)
            self.phase_exclusions.blockSignals(False)
            if self.phase_exclusions.rowCount():
                self.exclude_phases.setChecked(True)

        def _clear_phase_exclusions(self) -> None:
            self.phase_exclusions.blockSignals(True)
            for row in range(self.phase_exclusions.rowCount()):
                item = self.phase_exclusions.item(row, 0)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Unchecked)
            self.phase_exclusions.blockSignals(False)
            self.exclude_phases.setChecked(False)

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
            for widget in (self.components, self.saturated_components):
                for index in range(widget.count()):
                    widget.item(index).setCheckState(Qt.CheckState.Unchecked)
            self._clear_phase_exclusions()
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
            self.phase_exclusions.blockSignals(True)
            for index in range(self.phase_exclusions.rowCount()):
                item = self.phase_exclusions.item(index, 0)
                if item is None:
                    continue
                item.setCheckState(
                    Qt.CheckState.Checked
                    if item.data(Qt.ItemDataRole.UserRole) in selected
                    else Qt.CheckState.Unchecked
                )
            self.phase_exclusions.blockSignals(False)

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
                excluded_phase_names=self._checked_phase_exclusions(),
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
            detected_vectorcraft = which("vectorcraft.exe") or which("vectorcraft") or ""
            self.vectorcraft_edit = QLineEdit(
                self._settings.value("vectorcraft_executable", detected_vectorcraft, type=str)
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
            paths.addRow("VectorCraft executable (optional)", self._path_row(
                self.vectorcraft_edit, "Select VectorCraft", False
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
            vectorcraft_path = self.vectorcraft_edit.text().strip()
            if vectorcraft_path and not Path(vectorcraft_path).is_file():
                QMessageBox.warning(
                    self, "VectorCraft not found", "Choose the VectorCraft executable or clear the field."
                )
                return
            self._settings.setValue("installation_path", self.installation_edit.text().strip())
            self._settings.setValue("default_project_directory", str(project_folder))
            self._settings.setValue("vectorcraft_executable", vectorcraft_path)
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
            self.vectorcraft_edit.setText(which("vectorcraft.exe") or which("vectorcraft") or "")
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
            self.resize(1360, 820)
            self.setMinimumSize(1040, 680)
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
                QSplitter::handle { background: #ddd6fe; width: 3px; }
                QLabel#workspaceTitle {
                    background: #f5f3ff; color: #3b1b75; border: 1px solid #ddd6fe;
                    border-radius: 8px; padding: 9px 12px; font-size: 15px; font-weight: 700;
                }
                QLabel#panelDescription { color: #5b5680; padding: 2px 3px 7px 3px; }
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
            self._stage = ""
            self._stage_output = ""
            self._stage_had_perplex_error = False
            self._base_svg_path: Path | None = None
            self._vectorcraft_svg_path: Path | None = None
            self._figure_size = 800
            self._zoom_factor = 1.0
            self._phase_regions: list[dict[str, object]] = []
            self._draft_region: list[tuple[int, int]] = []
            self._drawing_phase_region = False
            self._placing_text_box = False
            self._text_annotations: list[dict[str, object]] = []

            self.installation_edit = QLineEdit(
                self._settings.value("installation_path", "", type=str)
            )
            self.project_edit = QLineEdit(self._settings.value("project_path", "", type=str))
            self.run_button = QPushButton("Run Perple_X Calculation")
            self.run_button.clicked.connect(self._run_convex)
            self.save_figure_button = QPushButton("Save Figure As…")
            self.save_figure_button.setEnabled(False)
            self.save_figure_button.clicked.connect(self._save_figure_as)
            self.open_vectorcraft_button = QPushButton("Edit in VectorCraft…")
            self.open_vectorcraft_button.setEnabled(False)
            self.open_vectorcraft_button.clicked.connect(self._open_in_vectorcraft)
            self.reload_vectorcraft_button = QPushButton("Reload Edited SVG")
            self.reload_vectorcraft_button.setEnabled(False)
            self.reload_vectorcraft_button.clicked.connect(self._reload_vectorcraft_svg)
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
            self.figure = VectorFigureWidget()
            self.figure.set_overlay_callback(self._paint_figure_overlays)
            self.figure_scroll = FigurePreviewScrollArea()
            self.figure_scroll.setStyleSheet("QScrollArea { background: white; border: 1px solid #d9e2ec; }")
            self.figure_scroll.setBackgroundRole(self.figure.backgroundRole())
            self.figure_scroll.setWidget(self.figure)
            self.figure_scroll.set_annotation_click_callback(self._add_phase_region_vertex)
            self.figure_scroll.setWidgetResizable(False)
            self.figure_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self.build_editor = BuildEditor(self.installation_edit, self._use_created_project)
            self.build_editor.refresh_files()
            self.settings_page = SettingsPage(self._apply_settings, self._create_desktop_shortcut)

            form = QFormLayout()
            form.addRow("Perple_X installation", self._path_row(self.installation_edit, self._choose_installation))
            form.addRow("Project definition (.dat)", self._path_row(self.project_edit, self._choose_project))

            figure_layout = QVBoxLayout()
            figure_layout.setContentsMargins(10, 10, 10, 10)
            figure_layout.addLayout(form)
            actions = QHBoxLayout()
            actions.addWidget(self.run_button)
            actions.addWidget(self.save_figure_button)
            actions.addWidget(self.open_vectorcraft_button)
            actions.addWidget(self.reload_vectorcraft_button)
            actions.addStretch()
            figure_layout.addLayout(actions)
            figure_header = QHBoxLayout()
            figure_header.addWidget(QLabel("Native vector preview (SVG) — hold Space and drag to pan"))
            figure_header.addStretch()
            figure_header.addWidget(self.zoom_out_button)
            figure_header.addWidget(self.zoom_in_button)
            figure_header.addWidget(self.reset_zoom_button)
            figure_layout.addLayout(figure_header)
            drawing_toolbar = QWidget()
            drawing_toolbar.setObjectName("drawingToolbar")
            drawing_toolbar.setFixedWidth(102)
            drawing_tools = QVBoxLayout(drawing_toolbar)
            drawing_tools.setContentsMargins(6, 8, 6, 8)
            drawing_tools.setSpacing(8)
            drawing_label = QLabel("DRAW")
            drawing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            drawing_label.setStyleSheet("font-weight: 700; color: #5b21b6;")
            drawing_tools.addWidget(drawing_label)
            self.select_figure_tool_button = QToolButton()
            self.select_figure_tool_button.setText("↖\nSelect")
            self.select_figure_tool_button.setToolTip("Return to figure selection mode")
            self.start_phase_region_button = QToolButton()
            self.start_phase_region_button.setText("⬠\nRegion")
            self.start_phase_region_button.setToolTip("Draw a colored phase region on the figure")
            self.start_phase_region_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            self.text_box_tool_button = QToolButton()
            self.text_box_tool_button.setText("T\nText Box")
            self.text_box_tool_button.setToolTip("Place a free text box on the figure")
            self.finish_phase_region_button = QToolButton()
            self.finish_phase_region_button.setText("✓\nFinish")
            self.finish_phase_region_button.setToolTip("Finish and label the current phase region")
            self.cancel_phase_region_button = QToolButton()
            self.cancel_phase_region_button.setText("×\nCancel")
            self.cancel_phase_region_button.setToolTip("Cancel the current phase region")
            self.undo_phase_vertex_button = QToolButton()
            self.undo_phase_vertex_button.setText("↶\nUndo point")
            self.undo_phase_vertex_button.setToolTip("Remove the last boundary point")
            self.delete_phase_region_button = QToolButton()
            self.delete_phase_region_button.setText("−\nDelete")
            self.delete_phase_region_button.setToolTip("Delete the selected colored phase region")
            self.open_modifier_tool_button = QToolButton()
            self.open_modifier_tool_button.setText("⚙\nDiagram\nModifier")
            self.open_modifier_tool_button.setToolTip("Open figure appearance, phase labels, and color settings")
            for tool in (
                self.select_figure_tool_button,
                self.start_phase_region_button,
                self.text_box_tool_button,
                self.finish_phase_region_button,
                self.undo_phase_vertex_button,
                self.cancel_phase_region_button,
                self.delete_phase_region_button,
                self.open_modifier_tool_button,
            ):
                tool.setMinimumSize(84, 44)
                tool.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                drawing_tools.addWidget(tool)
            self.open_modifier_tool_button.setMinimumHeight(62)
            drawing_tools.addStretch()
            drawing_toolbar.setStyleSheet(
                "QWidget#drawingToolbar { background: #f7f5ff; border: 1px solid #ddd6fe; "
                "border-radius: 8px; } QToolButton { color: #3b276a; background: white; "
                "border: 1px solid #c4b5fd; border-radius: 6px; padding: 5px; font-weight: 600; } "
                "QToolButton:hover { background: #ede9fe; border-color: #7c3aed; }"
            )
            self.start_phase_region_button.clicked.connect(self._start_phase_region)
            self.text_box_tool_button.clicked.connect(self._start_text_box_tool)
            self.select_figure_tool_button.clicked.connect(self._select_figure_tool)
            self.finish_phase_region_button.clicked.connect(self._finish_phase_region)
            self.cancel_phase_region_button.clicked.connect(self._cancel_phase_region)
            self.undo_phase_vertex_button.clicked.connect(self._undo_phase_region_vertex)
            self.delete_phase_region_button.clicked.connect(self._delete_phase_region)
            self.open_modifier_tool_button.clicked.connect(self._open_diagram_modifier)
            preview_row = QHBoxLayout()
            preview_row.setSpacing(8)
            preview_row.addWidget(drawing_toolbar)
            preview_row.addWidget(self.figure_scroll, 1)
            figure_layout.addLayout(preview_row, 1)
            figure_page = QWidget()
            figure_page.setLayout(figure_layout)

            console_layout = QVBoxLayout()
            console_layout.setContentsMargins(10, 10, 10, 10)
            console_description = QLabel(
                "Live Perple_X output and diagnostics for the active calculation."
            )
            console_description.setObjectName("panelDescription")
            console_layout.addWidget(console_description)
            console_layout.addWidget(self.log, 1)
            console_page = QWidget()
            console_page.setLayout(console_layout)

            self.modifier_title = QLineEdit()
            self.modifier_title.setPlaceholderText("Optional publication title")
            self.modifier_path_color = QComboBox()
            self.modifier_path_color.addItem("Purple", "#6d28d9")
            self.modifier_path_color.addItem("Black", "#1f1b2d")
            self.modifier_path_color.addItem("Red", "#dc2626")
            self.modifier_path_color.addItem("Blue", "#2563eb")
            self.modifier_path_width = self._modifier_number(2.0)
            self.modifier_path_width.setRange(1.0, 12.0)
            self.modifier_path_width.setSuffix(" px")
            self.modifier_t_min = self._modifier_number(0.0)
            self.modifier_t_max = self._modifier_number(1.0)
            self.modifier_p_min = self._modifier_number(0.0)
            self.modifier_p_max = self._modifier_number(1.0)
            self.path_table = QTableWidget(0, 2)
            self.path_table.setHorizontalHeaderLabels(("T (K)", "P (bar)"))
            self.path_table.verticalHeader().setVisible(False)
            self.path_table.setMaximumHeight(185)
            self.path_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self.add_path_point_button = QPushButton("Add P–T Point")
            self.example_path_button = QPushButton("Insert Example Path")
            self.remove_path_point_button = QPushButton("Remove Selected Point")
            self.apply_diagram_button = QPushButton("Open Figure Preview")
            self.reset_diagram_button = QPushButton("Reset Diagram Changes")
            self.add_path_point_button.clicked.connect(self._add_path_point)
            self.example_path_button.clicked.connect(self._insert_example_path)
            self.remove_path_point_button.clicked.connect(self._remove_path_point)
            self.apply_diagram_button.clicked.connect(self._apply_diagram_modifications)
            self.reset_diagram_button.clicked.connect(self._reset_diagram_modifier)
            self.modifier_title.textChanged.connect(self._refresh_diagram_preview)
            self.modifier_path_color.currentIndexChanged.connect(self._refresh_diagram_preview)
            self.modifier_path_width.valueChanged.connect(self._refresh_diagram_preview)
            for field in (
                self.modifier_t_min,
                self.modifier_t_max,
                self.modifier_p_min,
                self.modifier_p_max,
            ):
                field.valueChanged.connect(self._refresh_diagram_preview)

            modifier_layout = QVBoxLayout()
            modifier_layout.setContentsMargins(10, 10, 10, 10)
            modifier_layout.setSpacing(14)
            modifier_intro = QLabel(
                "The Perple_X drawing is rendered as vector geometry in Studio. Add editable "
                "display-only annotations here; these changes never alter the calculation or "
                "its stable assemblages."
            )
            modifier_intro.setObjectName("panelDescription")
            modifier_intro.setWordWrap(True)
            modifier_layout.addWidget(modifier_intro)
            title_form = QFormLayout()
            title_form.addRow("Figure title", self.modifier_title)
            modifier_layout.addWidget(self._modifier_box("Figure appearance", title_form))
            path_form = QFormLayout()
            path_form.addRow("Path color", self.modifier_path_color)
            path_form.addRow("Line width", self.modifier_path_width)
            modifier_layout.addWidget(self._modifier_box("P–T path overlay", path_form))
            modifier_layout.addWidget(QLabel("Path points"))
            modifier_layout.addWidget(self.path_table)
            path_actions = QHBoxLayout()
            path_actions.addWidget(self.add_path_point_button)
            path_actions.addWidget(self.example_path_button)
            path_actions.addWidget(self.remove_path_point_button)
            path_actions.addStretch()
            modifier_layout.addLayout(path_actions)
            axes_form = QGridLayout()
            axes_form.addWidget(QLabel("T (K) min / max"), 0, 0)
            axes_form.addWidget(self.modifier_t_min, 0, 1)
            axes_form.addWidget(self.modifier_t_max, 0, 2)
            axes_form.addWidget(QLabel("P (bar) min / max"), 1, 0)
            axes_form.addWidget(self.modifier_p_min, 1, 1)
            axes_form.addWidget(self.modifier_p_max, 1, 2)
            modifier_layout.addWidget(self._modifier_box("Diagram axes for the overlay", axes_form))

            self.phase_name = QLineEdit()
            self.phase_name.setPlaceholderText("For example: Sillimanite")
            self.phase_color = QComboBox()
            for name, color in (
                ("Lavender", "#b9b6d9"),
                ("Apricot", "#fde0ba"),
                ("Mint", "#b7e4c7"),
                ("Sky blue", "#b8d8ee"),
                ("Rose", "#f5c2c7"),
                ("Yellow", "#f9e79f"),
            ):
                self.phase_color.addItem(name, color)
            self.phase_opacity = QSpinBox()
            self.phase_opacity.setRange(10, 90)
            self.phase_opacity.setValue(55)
            self.phase_opacity.setSuffix(" %")
            self.phase_regions_table = QTableWidget(0, 2)
            self.phase_regions_table.setHorizontalHeaderLabels(("Phase name", "Fill color"))
            self.phase_regions_table.verticalHeader().setVisible(False)
            self.phase_regions_table.setMaximumHeight(145)
            self.phase_regions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self.phase_regions_table.itemChanged.connect(self._update_phase_region_from_table)
            self.text_boxes_table = QTableWidget(0, 2)
            self.text_boxes_table.setHorizontalHeaderLabels(("Text box content", "Placed at (px)"))
            self.text_boxes_table.verticalHeader().setVisible(False)
            self.text_boxes_table.setMaximumHeight(150)
            self.text_boxes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self.text_boxes_table.itemChanged.connect(self._update_text_box_from_table)
            self.edit_text_box_button = QPushButton("Edit Selected Text Box…")
            self.edit_text_box_button.clicked.connect(self._edit_selected_text_box)
            self.remove_text_box_button = QPushButton("Remove Selected Text Box")
            self.remove_text_box_button.clicked.connect(self._remove_selected_text_box)
            phase_form = QFormLayout()
            phase_form.addRow("Phase name", self.phase_name)
            phase_form.addRow("Fill color", self.phase_color)
            phase_form.addRow("Opacity", self.phase_opacity)
            phase_box_layout = QVBoxLayout()
            phase_box_layout.addLayout(phase_form)
            phase_help = QLabel(
                "Set the phase name and fill style here. In Figure, choose Region on the left "
                "toolbar, click boundary points, then choose Finish. Phase names are kept in this "
                "list; use Text Box to place visible labels anywhere."
            )
            phase_help.setWordWrap(True)
            phase_help.setObjectName("panelDescription")
            phase_box_layout.addWidget(phase_help)
            phase_box_layout.addWidget(self.phase_regions_table)
            modifier_layout.addWidget(self._modifier_box("Phase region colors", phase_box_layout))
            text_box_layout = QVBoxLayout()
            text_box_help = QLabel(
                "Choose Text Box on the left toolbar and click the figure to place text. "
                "Select an entry and choose Edit Selected Text Box to change its text."
            )
            text_box_help.setWordWrap(True)
            text_box_help.setObjectName("panelDescription")
            text_box_layout.addWidget(text_box_help)
            text_box_layout.addWidget(self.text_boxes_table)
            text_box_layout.addWidget(self.edit_text_box_button)
            text_box_layout.addWidget(self.remove_text_box_button)
            modifier_layout.addWidget(self._modifier_box("Text boxes", text_box_layout))
            verification_note = QLabel(
                "The overlay uses the standard PSSECT plot frame. Check path alignment before "
                "using an exported figure in a publication."
            )
            verification_note.setWordWrap(True)
            verification_note.setObjectName("panelDescription")
            modifier_layout.addWidget(verification_note)
            modifier_actions = QHBoxLayout()
            modifier_actions.addWidget(self.apply_diagram_button)
            modifier_actions.addWidget(self.reset_diagram_button)
            modifier_actions.addStretch()
            modifier_layout.addLayout(modifier_actions)
            modifier_layout.addStretch()
            modifier_page = QWidget()
            modifier_page.setLayout(modifier_layout)
            modifier_scroll = QScrollArea()
            modifier_scroll.setWidget(modifier_page)
            modifier_scroll.setWidgetResizable(True)
            modifier_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            modifier_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.modifier_scroll = modifier_scroll

            build_scroll = QScrollArea()
            build_scroll.setWidget(self.build_editor)
            build_scroll.setWidgetResizable(True)
            build_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.configuration_tabs = QTabWidget()
            self.configuration_tabs.addTab(build_scroll, "BUILD Setup")
            self.configuration_tabs.addTab(self.settings_page, "Settings")
            self.result_tabs = QTabWidget()
            self.result_tabs.addTab(figure_page, "Figure")
            self.result_tabs.addTab(console_page, "Console")
            self.result_tabs.addTab(modifier_scroll, "Diagram Modifier")

            configuration_panel = QWidget()
            configuration_layout = QVBoxLayout(configuration_panel)
            configuration_layout.setContentsMargins(8, 8, 6, 8)
            configuration_title = QLabel("Configuration")
            configuration_title.setObjectName("workspaceTitle")
            configuration_layout.addWidget(configuration_title)
            configuration_layout.addWidget(self.configuration_tabs, 1)
            results_panel = QWidget()
            results_layout = QVBoxLayout(results_panel)
            results_layout.setContentsMargins(6, 8, 8, 8)
            results_title = QLabel("Results and visualization")
            results_title.setObjectName("workspaceTitle")
            results_layout.addWidget(results_title)
            results_layout.addWidget(self.result_tabs, 1)
            self.workspace = QSplitter(Qt.Orientation.Horizontal)
            self.workspace.addWidget(configuration_panel)
            self.workspace.addWidget(results_panel)
            self.workspace.setChildrenCollapsible(False)
            self.workspace.setStretchFactor(0, 0)
            self.workspace.setStretchFactor(1, 1)
            self.workspace.setSizes((460, 820))
            self.setCentralWidget(self.workspace)
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

        @staticmethod
        def _modifier_number(value: float) -> QDoubleSpinBox:
            field = QDoubleSpinBox()
            field.setLocale(QLocale.c())
            field.setRange(-1.0e12, 1.0e12)
            field.setDecimals(4)
            field.setValue(value)
            return field

        @staticmethod
        def _modifier_box(title: str, layout: object) -> QGroupBox:
            box = QGroupBox(title)
            box.setLayout(layout)
            return box

        def _set_modifier_axes_from_project(self, project: str | Path) -> None:
            """Load P-T limits from standard Perple_X project comments when available."""
            try:
                lines = Path(project).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                return
            values: dict[str, list[float]] = {}
            for line in lines:
                lowered = line.casefold()
                if "max p, t" not in lowered and "min p, t" not in lowered:
                    continue
                numbers = [float(value) for value in re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", line)]
                if len(numbers) >= 2:
                    values["max" if "max p, t" in lowered else "min"] = numbers[:2]
            if "min" in values and "max" in values:
                self.modifier_p_min.setValue(values["min"][0])
                self.modifier_p_max.setValue(values["max"][0])
                self.modifier_t_min.setValue(values["min"][1])
                self.modifier_t_max.setValue(values["max"][1])

        def _add_path_point(self) -> None:
            row = self.path_table.rowCount()
            self.path_table.insertRow(row)
            first = row == 0
            temperature = self._modifier_number(
                self.modifier_t_min.value() if first else self.modifier_t_max.value()
            )
            pressure = self._modifier_number(
                self.modifier_p_min.value() if first else self.modifier_p_max.value()
            )
            self.path_table.setCellWidget(row, 0, temperature)
            self.path_table.setCellWidget(row, 1, pressure)
            temperature.valueChanged.connect(self._refresh_diagram_preview)
            pressure.valueChanged.connect(self._refresh_diagram_preview)
            self._refresh_diagram_preview()

        def _insert_example_path(self) -> None:
            """Insert a clearly visible path so users can verify the modifier is active."""
            self.path_table.setRowCount(0)
            t_range = self.modifier_t_max.value() - self.modifier_t_min.value()
            p_range = self.modifier_p_max.value() - self.modifier_p_min.value()
            if t_range <= 0 or p_range <= 0:
                QMessageBox.warning(
                    self,
                    "Set diagram axes first",
                    "Choose a project with valid P–T limits before inserting an example path.",
                )
                return
            for fraction in (0.25, 0.5, 0.75):
                row = self.path_table.rowCount()
                self.path_table.insertRow(row)
                temperature = self._modifier_number(self.modifier_t_min.value() + t_range * fraction)
                pressure = self._modifier_number(self.modifier_p_min.value() + p_range * fraction)
                self.path_table.setCellWidget(row, 0, temperature)
                self.path_table.setCellWidget(row, 1, pressure)
                temperature.valueChanged.connect(self._refresh_diagram_preview)
                pressure.valueChanged.connect(self._refresh_diagram_preview)
            self._refresh_diagram_preview()

        def _remove_path_point(self) -> None:
            row = self.path_table.currentRow()
            if row >= 0:
                self.path_table.removeRow(row)
                self._refresh_diagram_preview()

        def _path_points(self) -> list[tuple[float, float]]:
            points: list[tuple[float, float]] = []
            for row in range(self.path_table.rowCount()):
                temperature = self.path_table.cellWidget(row, 0)
                pressure = self.path_table.cellWidget(row, 1)
                if isinstance(temperature, QDoubleSpinBox) and isinstance(pressure, QDoubleSpinBox):
                    points.append((temperature.value(), pressure.value()))
            return points

        def _start_phase_region(self) -> None:
            if self._base_svg_path is None:
                QMessageBox.information(
                    self, "No figure yet", "Run a calculation before adding a colored phase region."
                )
                return
            self._placing_text_box = False
            self._drawing_phase_region = True
            self._draft_region = []
            self.figure.setCursor(Qt.CursorShape.CrossCursor)
            self.result_tabs.setCurrentIndex(0)
            self.statusBar().showMessage(
                "Click boundary points in the Figure preview. Select Finish Region when done."
            )

        def _select_figure_tool(self) -> None:
            self._drawing_phase_region = False
            self._placing_text_box = False
            self.figure.unsetCursor()
            self._refresh_diagram_preview()
            self.statusBar().showMessage("Selection mode. Choose Region to continue drawing.")

        def _start_text_box_tool(self) -> None:
            if self._base_svg_path is None:
                QMessageBox.information(
                    self, "No figure yet", "Run a calculation before adding a text box."
                )
                return
            self._drawing_phase_region = False
            self._placing_text_box = True
            self.figure.setCursor(Qt.CursorShape.IBeamCursor)
            self.result_tabs.setCurrentIndex(0)
            self.statusBar().showMessage("Click the figure where the text box should begin.")

        def _open_diagram_modifier(self) -> None:
            self.result_tabs.setCurrentWidget(self.modifier_scroll)

        def _update_phase_region_from_table(self, item: QTableWidgetItem) -> None:
            """Apply inline edits to a phase-region name and redraw the preview."""
            if item.column() != 0:
                return
            row = item.row()
            if row < 0 or row >= len(self._phase_regions):
                return
            label = item.text().strip()
            if not label:
                label = str(self._phase_regions[row]["label"])
                item.setText(label)
                return
            self._phase_regions[row]["label"] = label
            self._refresh_diagram_preview()
            self.statusBar().showMessage(f"Phase label updated: {label}")

        def _update_text_box_from_table(self, item: QTableWidgetItem) -> None:
            if item.column() != 0:
                return
            row = item.row()
            if row < 0 or row >= len(self._text_annotations):
                return
            self._text_annotations[row]["text"] = item.text()
            self._refresh_diagram_preview()

        def _cancel_phase_region(self) -> None:
            self._drawing_phase_region = False
            self._placing_text_box = False
            self._draft_region = []
            self.figure.unsetCursor()
            self._refresh_diagram_preview()
            self.statusBar().showMessage("Phase-region drawing cancelled.")

        def _undo_phase_region_vertex(self) -> None:
            if not self._drawing_phase_region or not self._draft_region:
                self.statusBar().showMessage("There is no boundary point to undo.")
                return
            self._draft_region.pop()
            self._refresh_diagram_preview()
            self.statusBar().showMessage(
                f"Removed the last point. {len(self._draft_region)} boundary point(s) remain."
            )

        def _add_phase_region_vertex(self, position: object) -> bool:
            if self._base_svg_path is None:
                return False
            x = round(position.x() / self._zoom_factor)
            y = round(position.y() / self._zoom_factor)
            x = max(0, min(self._figure_size - 1, x))
            y = max(0, min(self._figure_size - 1, y))
            if self._placing_text_box:
                text, accepted = QInputDialog.getMultiLineText(
                    self, "Add text box", "Enter the text to place on the figure:"
                )
                if accepted and text.strip():
                    self._text_annotations.append({"text": text.strip(), "x": x, "y": y})
                    row = self.text_boxes_table.rowCount()
                    self.text_boxes_table.insertRow(row)
                    text_item = QTableWidgetItem(text.strip())
                    text_item.setFlags(text_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    self.text_boxes_table.setItem(row, 0, text_item)
                    position_item = QTableWidgetItem(f"{x}, {y}")
                    position_item.setFlags(position_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.text_boxes_table.setItem(row, 1, position_item)
                    self.statusBar().showMessage(
                        "Text box added. Edit its text in the Diagram Modifier list."
                    )
                self._placing_text_box = False
                self.figure.unsetCursor()
                self._refresh_diagram_preview()
                return True
            if not self._drawing_phase_region:
                return False
            self._draft_region.append((x, y))
            self._refresh_diagram_preview()
            self.statusBar().showMessage(
                f"Added boundary point {len(self._draft_region)}. Add more or select Finish Region."
            )
            return True

        def _finish_phase_region(self) -> None:
            if not self._drawing_phase_region:
                QMessageBox.information(
                    self, "Start a region", "Select Start Region before choosing boundary points.")
                return
            if len(self._draft_region) < 3:
                QMessageBox.warning(
                    self, "More points needed", "A phase region needs at least three boundary points.")
                return
            label = self.phase_name.text().strip() or f"Phase {len(self._phase_regions) + 1}"
            region = {
                "label": label,
                "color": str(self.phase_color.currentData()),
                "opacity": self.phase_opacity.value(),
                "points": self._draft_region.copy(),
            }
            self._phase_regions.append(region)
            row = self.phase_regions_table.rowCount()
            self.phase_regions_table.insertRow(row)
            self.phase_regions_table.setItem(row, 0, QTableWidgetItem(label))
            color_item = QTableWidgetItem(self.phase_color.currentText())
            color_item.setBackground(QColor(str(region["color"])))
            self.phase_regions_table.setItem(row, 1, color_item)
            self._drawing_phase_region = False
            self._placing_text_box = False
            self._draft_region = []
            self.figure.unsetCursor()
            self._refresh_diagram_preview()
            self.statusBar().showMessage(f"Added colored region: {label}")

        def _delete_phase_region(self) -> None:
            row = self.phase_regions_table.currentRow()
            if row < 0:
                QMessageBox.information(
                    self, "Select a region", "Select a phase region in the table to delete it.")
                return
            del self._phase_regions[row]
            self.phase_regions_table.removeRow(row)
            self._refresh_diagram_preview()
            self.statusBar().showMessage("Selected phase region deleted.")

        def _remove_selected_text_box(self) -> None:
            row = self.text_boxes_table.currentRow()
            if row < 0:
                QMessageBox.information(
                    self, "Select a text box", "Select a text box in the list to remove it."
                )
                return
            del self._text_annotations[row]
            self.text_boxes_table.removeRow(row)
            self._refresh_diagram_preview()
            self.statusBar().showMessage("Selected text box removed.")

        def _edit_selected_text_box(self) -> None:
            row = self.text_boxes_table.currentRow()
            if row < 0 or row >= len(self._text_annotations):
                QMessageBox.information(
                    self, "Select a text box", "Select a text box in the list to edit it."
                )
                return
            current_text = str(self._text_annotations[row]["text"])
            edited_text, accepted = QInputDialog.getMultiLineText(
                self, "Edit text box", "Update the figure text:", current_text
            )
            if accepted and edited_text.strip():
                self._text_annotations[row]["text"] = edited_text.strip()
                self.text_boxes_table.item(row, 0).setText(edited_text.strip())
                self._refresh_diagram_preview()
                self.statusBar().showMessage("Text box updated.")

        def _draw_phase_regions(self, painter: QPainter) -> None:
            """Paint user-created color/label layers in source-image pixel coordinates."""
            for region in self._phase_regions:
                points = region["points"]
                if not isinstance(points, list) or len(points) < 3:
                    continue
                path = QPainterPath()
                first_x, first_y = points[0]
                path.moveTo(first_x, first_y)
                for x, y in points[1:]:
                    path.lineTo(x, y)
                path.closeSubpath()
                fill = QColor(str(region["color"]))
                fill.setAlpha(int(region["opacity"]) * 255 // 100)
                painter.setBrush(fill)
                painter.setPen(QPen(QColor("#1f2937"), 1.5))
                painter.drawPath(path)
            if self._drawing_phase_region and self._draft_region:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#6d28d9"), 2, Qt.PenStyle.DashLine))
                for start, end in zip(self._draft_region, self._draft_region[1:]):
                    painter.drawLine(start[0], start[1], end[0], end[1])
                painter.setBrush(QColor("#6d28d9"))
                for x, y in self._draft_region:
                    painter.drawEllipse(x - 4, y - 4, 8, 8)

        def _draw_text_annotations(self, painter: QPainter) -> None:
            font = QFont("Segoe UI", max(10, round(self._figure_size / 105)))
            metrics = QFontMetrics(font)
            painter.setFont(font)
            for annotation in self._text_annotations:
                text = str(annotation["text"])
                x, y = int(annotation["x"]), int(annotation["y"])
                max_text_width = 280
                wrapped_lines: list[str] = []
                for paragraph in text.splitlines() or [""]:
                    current = ""
                    for word in paragraph.split():
                        candidate = f"{current} {word}".strip()
                        if current and metrics.horizontalAdvance(candidate) > max_text_width:
                            wrapped_lines.append(current)
                            current = word
                        else:
                            current = candidate
                    wrapped_lines.append(current)
                box_width = max(100, min(max_text_width + 16, max(
                    (metrics.horizontalAdvance(line) for line in wrapped_lines), default=0
                ) + 16))
                line_height = metrics.height()
                box_height = max(line_height + 12, len(wrapped_lines) * line_height + 12)
                painter.fillRect(x, y, box_width, box_height, QColor(255, 255, 255, 225))
                painter.setPen(QPen(QColor("#4c1d95"), 1.5))
                painter.drawRect(x, y, box_width, box_height)
                painter.setPen(QPen(QColor("#1f1b2d")))
                for line_index, line in enumerate(wrapped_lines):
                    painter.drawText(
                        x + 8,
                        y + 6 + metrics.ascent() + line_index * line_height,
                        line,
                    )

        def _paint_figure_overlays(self, painter: QPainter) -> None:
            """Draw Studio's overlays as native vector strokes on top of the SVG."""
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            title = self.modifier_title.text().strip()
            if title:
                title_font = QFont("Segoe UI", max(11, round(self._figure_size / 75)))
                title_font.setBold(True)
                painter.setFont(title_font)
                painter.setPen(QPen(QColor("#2e1065")))
                painter.drawText(
                    0, round(self._figure_size * 0.035), self._figure_size,
                    round(self._figure_size * 0.06),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, title,
                )
            points = self._path_points()
            t_min, t_max = self.modifier_t_min.value(), self.modifier_t_max.value()
            p_min, p_max = self.modifier_p_min.value(), self.modifier_p_max.value()
            if points and t_min < t_max and p_min < p_max:
                left, top = round(self._figure_size * 0.175), round(self._figure_size * 0.277)
                width, height = round(self._figure_size * 0.725), round(self._figure_size * 0.514)
                painter.save()
                painter.setClipRect(left, top, width, height)
                color = QColor(self.modifier_path_color.currentData())
                painter.setPen(QPen(color, self.modifier_path_width.value()))
                mapped = [
                    (
                        left + ((temperature - t_min) / (t_max - t_min)) * width,
                        top + (1 - (pressure - p_min) / (p_max - p_min)) * height,
                    )
                    for temperature, pressure in points
                ]
                for start, end in zip(mapped, mapped[1:]):
                    painter.drawLine(round(start[0]), round(start[1]), round(end[0]), round(end[1]))
                painter.setBrush(color)
                for x, y in mapped:
                    painter.drawEllipse(round(x) - 4, round(y) - 4, 8, 8)
                painter.restore()
            self._draw_phase_regions(painter)
            self._draw_text_annotations(painter)
            painter.restore()

        def _refresh_diagram_preview(self, *_args: object) -> None:
            """Refresh quietly while the user edits a modifier control."""
            if self._base_svg_path is None:
                return
            points = self._path_points()
            if points and (
                self.modifier_t_min.value() >= self.modifier_t_max.value()
                or self.modifier_p_min.value() >= self.modifier_p_max.value()
            ):
                return
            self._apply_diagram_modifications(show_figure=False, show_errors=False)

        def _apply_diagram_modifications(
            self, _checked: bool = False, *, show_figure: bool = True, show_errors: bool = True
        ) -> None:
            if self._base_svg_path is None:
                if show_errors:
                    QMessageBox.information(
                        self, "No figure yet", "Run a calculation before modifying its figure."
                    )
                return
            t_min, t_max = self.modifier_t_min.value(), self.modifier_t_max.value()
            p_min, p_max = self.modifier_p_min.value(), self.modifier_p_max.value()
            points = self._path_points()
            if points and (t_min >= t_max or p_min >= p_max):
                if show_errors:
                    QMessageBox.warning(
                        self, "Invalid diagram axes", "The overlay needs a valid increasing T and P range."
                    )
                return
            self.figure.update()
            if show_figure:
                self._zoom_factor = 1.0
            self._apply_zoom()
            if show_figure:
                self.result_tabs.setCurrentIndex(0)
                self.statusBar().showMessage("Diagram edits are rendered as vector graphics in Studio.")

        def _reset_diagram_modifier(self) -> None:
            self.modifier_title.clear()
            self.path_table.setRowCount(0)
            self.modifier_path_color.setCurrentIndex(0)
            self.modifier_path_width.setValue(2.0)
            self._phase_regions.clear()
            self.phase_regions_table.setRowCount(0)
            self._text_annotations.clear()
            self.text_boxes_table.setRowCount(0)
            self._drawing_phase_region = False
            self._placing_text_box = False
            self._draft_region = []
            self.figure.unsetCursor()
            if self._base_svg_path is not None:
                self._zoom_factor = 1.0
                self._apply_zoom()
                self.statusBar().showMessage("Diagram preview restored to the original figure.")

        def _choose_installation(self) -> None:
            directory = QFileDialog.getExistingDirectory(
                self, "Select Perple_X installation folder", self.installation_edit.text()
            )
            if directory:
                self.installation_edit.setText(directory)
                self.build_editor.refresh_files()

        def _use_created_project(self, project_file: Path) -> None:
            self.project_edit.setText(str(project_file))
            self._set_modifier_axes_from_project(project_file)
            self.result_tabs.setCurrentIndex(0)
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
                self._set_modifier_axes_from_project(filename)

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
            self.log.clear()
            self.save_figure_button.setEnabled(False)
            self._base_svg_path = None
            self._vectorcraft_svg_path = None
            self.open_vectorcraft_button.setEnabled(False)
            self.reload_vectorcraft_button.setEnabled(False)
            self._phase_regions.clear()
            self.phase_regions_table.setRowCount(0)
            self._text_annotations.clear()
            self.text_boxes_table.setRowCount(0)
            self._drawing_phase_region = False
            self._placing_text_box = False
            self._draft_region = []
            self._zoom_factor = 1.0
            for button in (self.zoom_out_button, self.zoom_in_button, self.reset_zoom_button):
                button.setEnabled(False)
            self.figure.clear()
            self.figure.set_reaction_equations([])
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
            self._stage_output = ""
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
                self._finish_with_error(f"Unknown calculation stage: {stage}")
                return

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
                self._stage_output += output
                if "**error" in output.casefold():
                    self._stage_had_perplex_error = True
                self._append_log(output)

        def _read_stderr(self) -> None:
            if self._process is not None:
                output = bytes(self._process.readAllStandardError()).decode(errors="replace")
                self._stage_output += output
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
                reaction_output = self._stage_output
                if project is not None:
                    print_file = project.working_directory / f"{project.project_name}.prn"
                    if print_file.is_file():
                        reaction_output += "\n" + print_file.read_text(
                            encoding="utf-8", errors="replace"
                        )
                self.figure.set_reaction_equations(self._parse_console_reactions(reaction_output))
                self._start_stage("PSVDRAW")
            elif stage == "VERTEX":
                self._start_stage("PSSECT")
            else:
                postscript = project.working_directory / f"{project.project_name}.ps"
                svg = project.working_directory / f"{project.project_name}.svg"
                try:
                    convert_postscript_to_svg(postscript, svg)
                except ValueError as error:
                    self._finish_with_error(str(error))
                    return
                if not self.figure.set_svg_file(svg):
                    self._finish_with_error(f"Studio could not load vector figure: {svg}")
                    return
                self._base_svg_path = svg
                self.open_vectorcraft_button.setEnabled(True)
                self._set_modifier_axes_from_project(project.project_file)
                self._zoom_factor = 1.0
                self._apply_zoom()
                message = f"Finished. Native vector preview: {svg}"
                self._append_log(f"\n{message}\n")
                self.statusBar().showMessage(message)
                self.run_button.setEnabled(True)
                self.save_figure_button.setEnabled(True)
                self.open_vectorcraft_button.setEnabled(True)
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
                str(Path.home() / f"{project_name}.svg"),
                "SVG vector figure (*.svg);;PNG image (*.png);;PostScript figure (*.ps)",
            )
            if not filename:
                return

            suffix = ".svg" if selected_filter.startswith("SVG") else ".png"
            if selected_filter.startswith("PostScript"):
                source = self._staged_project.working_directory / f"{project_name}.ps"
                suffix = ".ps"
            destination = Path(filename)
            if not destination.suffix:
                destination = destination.with_suffix(suffix)
            try:
                if selected_filter.startswith("PostScript"):
                    copy2(source, destination)
                elif selected_filter.startswith("SVG"):
                    self._write_vector_svg(destination)
                elif self._base_svg_path is not None:
                    output = QPixmap(self._figure_size, self.figure.natural_height)
                    output.fill(QColor("white"))
                    painter = QPainter(output)
                    self.figure.render_vector(
                        painter, QRectF(0, 0, self._figure_size, self.figure.natural_height)
                    )
                    painter.end()
                    if not output.save(str(destination), "PNG"):
                        raise OSError("Qt could not write the PNG image.")
                else:
                    raise OSError("No figure preview is available to export.")
            except OSError as error:
                QMessageBox.warning(self, "Could not save figure", str(error))
                return
            self.statusBar().showMessage(f"Figure saved: {destination}")
            self._append_log(f"Figure saved: {destination}\n")

        def _write_vector_svg(self, destination: Path) -> None:
            generator = QSvgGenerator()
            generator.setFileName(str(destination))
            generator.setSize(QSize(self._figure_size, self.figure.natural_height))
            generator.setViewBox(QRectF(0, 0, self._figure_size, self.figure.natural_height))
            painter = QPainter(generator)
            self.figure.render_vector(
                painter, QRectF(0, 0, self._figure_size, self.figure.natural_height)
            )
            painter.end()

        def _vectorcraft_executable(self) -> Path | None:
            configured = Path(self._settings.value("vectorcraft_executable", "", type=str))
            if configured.is_file():
                return configured
            located = which("vectorcraft.exe") or which("vectorcraft")
            if located:
                return Path(located)
            candidates = [
                Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "VectorCraft" / "vectorcraft.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "VectorCraft" / "vectorcraft.exe",
            ]
            return next((candidate for candidate in candidates if candidate.is_file()), None)

        def _open_in_vectorcraft(self) -> None:
            if self._staged_project is None or self._base_svg_path is None:
                QMessageBox.information(self, "No diagram yet", "Run a Perple_X calculation first.")
                return
            executable = self._vectorcraft_executable()
            if executable is None:
                QMessageBox.information(
                    self,
                    "VectorCraft is optional",
                    "Install VectorCraft, then select its executable in Settings.\n\n"
                    "The SVG editor is optional; Perple_X calculations and Studio's vector preview work without it.",
                )
                return
            project_name = self._staged_project.project_name
            project_folder = Path(self.project_edit.text()).expanduser().resolve().parent
            default_path = project_folder / f"{project_name}_figure.svg"
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save editable vector figure", str(default_path), "SVG vector figure (*.svg)"
            )
            if not filename:
                return
            destination = Path(filename)
            if not destination.suffix:
                destination = destination.with_suffix(".svg")
            try:
                self._write_vector_svg(destination)
                if not self.figure.set_svg_file(destination):
                    raise OSError("Studio could not reload the exported SVG.")
                self._base_svg_path = destination
                self._vectorcraft_svg_path = destination
                self._clear_baked_overlays()
                subprocess.Popen(
                    [str(executable), str(destination)],
                    cwd=str(destination.parent),
                    close_fds=True,
                )
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Could not open VectorCraft", str(error))
                return
            self.reload_vectorcraft_button.setEnabled(True)
            self.statusBar().showMessage(f"Opened editable SVG in VectorCraft: {destination}")

        def _clear_baked_overlays(self) -> None:
            """Promote exported overlays into the SVG baseline to avoid drawing them twice."""
            self.modifier_title.clear()
            self.path_table.setRowCount(0)
            self._phase_regions.clear()
            self.phase_regions_table.setRowCount(0)
            self._text_annotations.clear()
            self.text_boxes_table.setRowCount(0)
            self._draft_region = []
            self._drawing_phase_region = False
            self._placing_text_box = False

        def _reload_vectorcraft_svg(self) -> None:
            path = self._vectorcraft_svg_path
            if path is None or not path.is_file():
                QMessageBox.warning(self, "SVG not found", "The VectorCraft SVG file is no longer available.")
                return
            if not self.figure.set_svg_file(path):
                QMessageBox.warning(self, "Could not reload SVG", f"Studio could not read:\n{path}")
                return
            self._base_svg_path = path
            self._zoom_factor = 1.0
            self._apply_zoom()
            self.statusBar().showMessage(f"Reloaded VectorCraft edits: {path}")

        def _change_zoom(self, multiplier: float) -> None:
            if self._base_svg_path is None:
                return
            self._zoom_factor = max(0.2, min(5.0, self._zoom_factor * multiplier))
            self._apply_zoom()

        def _reset_zoom(self) -> None:
            if self._base_svg_path is None:
                return
            self._zoom_factor = 1.0
            self._apply_zoom()

        def _apply_zoom(self) -> None:
            if self._base_svg_path is None:
                return
            size = round(self._figure_size * self._zoom_factor)
            self.figure.resize(size, round(self.figure.natural_height * self._zoom_factor))
            self.figure.update()
            self.statusBar().showMessage(f"Figure zoom: {self._zoom_factor:.0%}")

        @staticmethod
        def _parse_console_reactions(output: str) -> list[tuple[int, str]]:
            """Read numbered reaction equations reported directly by CONVEX."""
            reactions: dict[int, str] = {}
            console_pattern = re.compile(
                r"finished\s+with\s+equilibrium\s*\(\s*(\d+)\s*\)\s*(.+?)\s*$",
                re.IGNORECASE,
            )
            print_pattern = re.compile(r"^\s*\(\s*(\d+)\s*-\s*\d+\s*\)\s*(.+?)\s*$")
            in_print_reaction_list = False
            for line in output.splitlines():
                lowered = line.casefold()
                if "univariant equilibria are summarized below" in lowered:
                    in_print_reaction_list = True
                    continue
                if "invariant points are summarized below" in lowered:
                    in_print_reaction_list = False
                    continue
                match = console_pattern.search(line.strip())
                if match is None and in_print_reaction_list:
                    match = print_pattern.search(line)
                if not match:
                    continue
                equation = " ".join(match.group(2).split())
                if equation:
                    reactions.setdefault(int(match.group(1)), equation)
            return sorted(reactions.items())

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
