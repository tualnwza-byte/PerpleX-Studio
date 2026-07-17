"""PySide6 desktop application entry point."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from shutil import copy2
from tempfile import gettempdir

from perplex_studio.perplex_installation import PerpleXInstallation
from perplex_studio.runner import StagedProject, find_ghostscript, stage_project


def main() -> None:
    """Start the PerpleX Studio desktop application."""
    try:
        from PySide6.QtCore import QProcess, QSettings, Qt
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import (
            QApplication,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QPlainTextEdit,
            QScrollArea,
            QStatusBar,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as error:
        raise SystemExit(
            "PySide6 is required. Activate the project environment and run: "
            'pip install -e ".[dev]"'
        ) from error

    class MainWindow(QMainWindow):
        """Minimal interface for running a staged Perple_X CONVEX project."""

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("PerpleX Studio")
            self.resize(920, 640)
            self.setStyleSheet("QMainWindow, QWidget { background: white; color: #1f2933; }")
            self._settings = QSettings("PerpleX Studio", "PerpleX Studio")
            self._process: QProcess | None = None
            self._staged_project: StagedProject | None = None
            self._installation: PerpleXInstallation | None = None
            self._ghostscript: Path | None = None
            self._stage = ""
            self._figure_pixmap: QPixmap | None = None
            self._zoom_factor = 1.0

            self.installation_edit = QLineEdit(
                self._settings.value("installation_path", "", type=str)
            )
            self.project_edit = QLineEdit(self._settings.value("project_path", "", type=str))
            self.run_button = QPushButton("Run CONVEX")
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
            self.log.setPlaceholderText("CONVEX console output will appear here.")
            self.figure = QLabel("The generated pseudosection preview will appear here.")
            self.figure.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.figure.setStyleSheet("QLabel { background: white; color: #52606d; }")
            self.figure_scroll = QScrollArea()
            self.figure_scroll.setStyleSheet("QScrollArea { background: white; border: 1px solid #d9e2ec; }")
            self.figure_scroll.setBackgroundRole(self.figure.backgroundRole())
            self.figure_scroll.setWidget(self.figure)
            self.figure_scroll.setWidgetResizable(False)
            self.figure_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

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
            container = QWidget()
            container.setLayout(layout)
            self.setCentralWidget(container)
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
            self._start_stage("CONVEX")

        def _start_stage(self, stage: str) -> None:
            if self._staged_project is None or self._installation is None:
                return
            self._stage = stage
            program: Path
            arguments: list[str] = []
            input_text = ""
            if stage == "CONVEX":
                program = self._installation.executables["convex.exe"]
                input_text = f"{self._staged_project.project_name}\n"
            elif stage == "PSVDRAW":
                program = self._installation.executables["psvdraw.exe"]
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
                self._append_log(bytes(self._process.readAllStandardOutput()).decode(errors="replace"))

        def _read_stderr(self) -> None:
            if self._process is not None:
                self._append_log(bytes(self._process.readAllStandardError()).decode(errors="replace"))

        def _process_finished(self, exit_code: int, _exit_status: object) -> None:
            self._read_stdout()
            self._read_stderr()
            stage = self._stage
            project = self._staged_project
            self._process = None
            if exit_code != 0 or project is None:
                self._finish_with_error(f"{stage} finished with exit code {exit_code}.")
                return
            if stage == "CONVEX":
                self._start_stage("PSVDRAW")
            elif stage == "PSVDRAW":
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
