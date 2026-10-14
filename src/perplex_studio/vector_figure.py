"""Import the structured EPS/PostScript figures written by Perple_X as SVG.

Perple_X 7.x writes an Idraw-style EPS file containing one block per graphic
primitive.  This module translates those primitives without invoking a
PostScript interpreter, so Studio can keep the figure as vector data.
"""

from __future__ import annotations

import html
import re
from pathlib import Path


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_BLOCK = re.compile(r"Begin %I (\w+)\s*(.*?)\s*End", re.DOTALL)


def _numbers(text: str) -> list[float]:
    return [float(value) for value in re.findall(_NUMBER, text)]


def _matrix(block: str) -> tuple[float, float, float, float, float, float]:
    matches = re.findall(r"\[([^\]]+)\]\s*concat", block)
    values = _numbers(matches[-1]) if matches else [1, 0, 0, 1, 0, 0]
    if len(values) != 6:
        raise ValueError("Unsupported Perple_X transformation matrix in EPS figure.")
    a, b, c, d, e, f = values
    # Perple_X EPS uses a page-level 0.8 scale and a y-up PostScript frame.
    return 0.8 * a, -0.8 * b, 0.8 * c, -0.8 * d, 0.8 * e, 800 - 0.8 * f


def _svg_matrix(matrix: tuple[float, float, float, float, float, float]) -> str:
    return "matrix(" + " ".join(f"{value:.8g}" for value in matrix) + ")"


def _style(block: str) -> tuple[str, str, str, float, str]:
    foreground = re.search(rf"({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s+SetCFg", block)
    background = re.search(rf"({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s+SetCBg", block)
    fg = tuple(float(value) for value in foreground.groups()) if foreground else (0, 0, 0)
    bg = tuple(float(value) for value in background.groups()) if background else (1, 1, 1)
    fill_match = re.search(rf"({_NUMBER})\s+SetP", block)
    fill_gray = float(fill_match.group(1)) if fill_match else None
    fill = "none"
    if fill_gray is not None:
        # SetP's gray value blends the foreground into the background.
        rgb = tuple(max(0, min(1, bg[i] + (fg[i] - bg[i]) * fill_gray)) for i in range(3))
        fill = "#" + "".join(f"{round(channel * 255):02x}" for channel in rgb)
    brush = re.search(r"([\d.]+)\s+0\s+0\s+\[([^\]]*)\]\s+\d+\s+SetB", block)
    stroke = "none"
    width = 0.0
    dash = ""
    if brush:
        width = float(brush.group(1))
        stroke = "#" + "".join(f"{round(max(0, min(1, c)) * 255):02x}" for c in fg)
        dashes = _numbers(brush.group(2))
        if dashes:
            dash = ' stroke-dasharray="' + ",".join(f"{n:g}" for n in dashes) + '"'
    return fill, stroke, dash, width, ""


def _point_list(text: str, count: int) -> list[tuple[float, float]]:
    values = _numbers(text)
    if len(values) < count * 2:
        return []
    values = values[-count * 2 :]
    return list(zip(values[0::2], values[1::2]))


def _text_element(block: str, transform: str) -> str:
    font_match = re.search(r"/([^\s/]+)\s+" + _NUMBER + r"\s+SetF", block)
    font = font_match.group(1) if font_match else "Helvetica"
    size = float(re.search(r"/[^\s/]+\s+(" + _NUMBER + r")\s+SetF", block).group(1)) if font_match else 14
    text_match = re.search(r"\[\s*\((.*?)\)\s*\]\s*Text", block, re.DOTALL)
    if not text_match:
        return ""
    label = text_match.group(1)
    label = re.sub(r"\\([\\()])", r"\1", label).replace(r"\n", " ")
    # Counteract the PostScript-to-SVG vertical-axis flip for upright glyphs.
    values = _numbers(transform)
    text_transform = (
        _svg_matrix((values[0], -values[1], values[2], -values[3], values[4], values[5]))
        if len(values) == 6 else transform
    )
    return (
        f'<text transform="{text_transform}" font-family="{html.escape(font)}" '
        f'font-size="{size:g}" fill="#000000">{html.escape(label)}</text>'
    )


def postscript_to_svg(source: str | Path) -> str:
    """Translate Perple_X's structured EPS primitives into a vector SVG document."""
    path = Path(source)
    try:
        contents = path.read_text(encoding="latin-1")
    except OSError as error:
        raise ValueError(f"Cannot read Perple_X PostScript figure: {error}") from error
    if not contents.startswith("%!PS-Adobe") or "Idraw 7 Grid" not in contents:
        raise ValueError("This is not a structured Perple_X EPS/PostScript figure.")

    elements: list[str] = []
    unsupported: set[str] = set()
    for match in _BLOCK.finditer(contents):
        kind, block = match.groups()
        if kind not in {"Line", "Poly", "MLine", "BSpl", "CBSpl", "Elli", "Text", "Rect"}:
            unsupported.add(kind)
            continue
        transform = _svg_matrix(_matrix(block))
        fill, stroke, dash, width, _ = _style(block)
        style = f'fill="{fill}" stroke="{stroke}" stroke-width="{width:g}"{dash}'
        if kind == "Text":
            element = _text_element(block, transform)
            if element:
                elements.append(element)
        elif kind == "Line":
            coords = re.search(rf"^\s*({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s*$", block, re.MULTILINE)
            if coords:
                x1, y1, x2, y2 = (float(value) for value in coords.groups())
                elements.append(f'<path d="M{x1:g},{y1:g} L{x2:g},{y2:g}" transform="{transform}" {style}/>')
        elif kind in {"Poly", "MLine", "BSpl", "CBSpl"}:
            command = re.search(rf"(?m)^\s*(\d+)\s+{kind}\s*$", block)
            if not command:
                continue
            count = int(command.group(1))
            points = _point_list(block[: command.start()], count)
            if not points:
                continue
            d = "M" + " L".join(f"{x:g},{y:g}" for x, y in points)
            if kind in {"Poly", "CBSpl"}:
                d += " Z"
            elements.append(f'<path d="{d}" transform="{transform}" {style}/>')
        elif kind == "Elli":
            command = re.search(rf"({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s+Elli", block)
            if command:
                x, y, rx, ry = (float(value) for value in command.groups())
                elements.append(f'<ellipse cx="{x:g}" cy="{y:g}" rx="{rx:g}" ry="{ry:g}" transform="{transform}" {style}/>')
        elif kind == "Rect":
            command = re.search(rf"({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s+Rect", block)
            if command:
                x, y, right, top = (float(value) for value in command.groups())
                width_rect, height_rect = right - x, top - y
                elements.append(f'<rect x="{x:g}" y="{y:g}" width="{width_rect:g}" height="{height_rect:g}" transform="{transform}" {style}/>')

    if not elements:
        detail = f" Unsupported objects: {', '.join(sorted(unsupported))}." if unsupported else ""
        raise ValueError("No supported vector objects were found in the Perple_X figure." + detail)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" '
        'viewBox="0 0 800 800" role="img">\n'
        '<rect width="800" height="800" fill="#ffffff"/>\n'
        + "\n".join(elements)
        + "\n</svg>\n"
    )


def convert_postscript_to_svg(source: str | Path, destination: str | Path) -> Path:
    """Convert one Perple_X EPS file to a durable, editable vector SVG file."""
    output = Path(destination)
    output.write_text(postscript_to_svg(source), encoding="utf-8")
    return output
