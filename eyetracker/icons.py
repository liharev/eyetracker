"""Логотип CAMAI: кольцо-«C», открытое вправо, и точка в центре.

Пропорции сняты с исходного изображения (1254×1254): внешний радиус кольца 457,
внутренний 278, точка 173, разрыв ±32°; цвета — белый #FDFCFD и бирюзовый #01F5E4.
В отличие от исходника логотип отцентрирован: центр кольца совпадает с центром полотна.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Iterable, Optional

WHITE = "#FDFCFD"
BLACK = "#000000"         # вариант для светлой темы оформления
CYAN = "#01F5E4"
GAP_DEG = 32.0
_SRC = 1254.0
R_OUT, R_IN, R_DOT = 457.2 / _SRC, 278.1 / _SRC, 173.3 / _SRC   # доли стороны полотна
TRAY_SCALE = 0.49 / R_OUT       # значок в трее занимает почти всё полотно (мелкий размер)
APP_ICON_ID = "camai-vigilance"


def icon_id(black: bool = False) -> str:
    return APP_ICON_ID + ("-black" if black else "")


def ring_color(black: bool = False) -> str:
    return BLACK if black else WHITE


def svg(size: int = 1024, ring: str = WHITE, dot: str = CYAN, scale: float = 1.0) -> str:
    """SVG-логотип (для ярлыков рабочего стола и документации)."""
    c = size / 2
    ro, ri, rd = (k * size * scale for k in (R_OUT, R_IN, R_DOT))
    g = math.radians(GAP_DEG)
    cos, sin = math.cos(g), math.sin(g)

    def pt(r, sign):
        return f"{c + r * cos:.2f},{c - sign * r * sin:.2f}"
    path = (f"M{pt(ro, 1)} A{ro:.2f},{ro:.2f} 0 1 0 {pt(ro, -1)} "
            f"L{pt(ri, -1)} A{ri:.2f},{ri:.2f} 0 1 1 {pt(ri, 1)} Z")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">\n'
            f'  <path d="{path}" fill="{ring}"/>\n'
            f'  <circle cx="{c:.2f}" cy="{c:.2f}" r="{rd:.2f}" fill="{dot}"/>\n</svg>\n')


# ----------------------------------------------------------------- Qt-часть
def _ring_path(size: float, scale: float):
    from .qt import QtCore, QtGui

    c = size / 2
    ro, ri = R_OUT * size * scale, R_IN * size * scale
    outer = QtCore.QRectF(c - ro, c - ro, 2 * ro, 2 * ro)
    inner = QtCore.QRectF(c - ri, c - ri, 2 * ri, 2 * ri)
    path = QtGui.QPainterPath()
    path.arcMoveTo(outer, GAP_DEG)
    path.arcTo(outer, GAP_DEG, 360 - 2 * GAP_DEG)        # через верх, левый край и низ
    path.arcTo(inner, 360 - GAP_DEG, -(360 - 2 * GAP_DEG))
    path.closeSubpath()
    return path


def render(size: int, ring: str = WHITE, dot: Optional[str] = CYAN, scale: float = 1.0, dot_mode: str = "filled"):
    """QImage с логотипом. dot_mode: filled | hollow | none | pause | cross."""
    from .qt import Qt, QtCore, QtGui

    img = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(ring))
    p.drawPath(_ring_path(size, scale))
    c = size / 2
    rd = R_DOT * size * scale
    color = QtGui.QColor(dot or ring)
    if dot_mode == "filled":
        p.setBrush(color)
        p.drawEllipse(QtCore.QPointF(c, c), rd, rd)
    elif dot_mode == "hollow":
        w = max(1.0, rd * 0.32)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QtGui.QPen(color, w))
        p.drawEllipse(QtCore.QPointF(c, c), rd - w / 2, rd - w / 2)
    elif dot_mode == "pause":
        bw, bh = rd * 0.55, rd * 1.8
        p.setBrush(color)
        p.drawRect(QtCore.QRectF(c - rd * 0.75, c - bh / 2, bw, bh))
        p.drawRect(QtCore.QRectF(c + rd * 0.2, c - bh / 2, bw, bh))
    elif dot_mode == "cross":
        p.setPen(QtGui.QPen(color, max(1.0, rd * 0.45), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        k = rd * 0.8
        p.drawLine(QtCore.QPointF(c - k, c - k), QtCore.QPointF(c + k, c + k))
        p.drawLine(QtCore.QPointF(c - k, c + k), QtCore.QPointF(c + k, c - k))
    p.end()
    return img


def app_icon(black: bool = False):
    """Цветной значок программы (окна, меню); black — чёрная «C» для светлой темы."""
    from .qt import QtGui

    icon = QtGui.QIcon()
    for s in (16, 22, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(QtGui.QPixmap.fromImage(render(s, ring_color(black))))
    return icon


def tray_icon(color: str, dot_mode: str = "filled"):
    """Монохромный значок для трея."""
    from .qt import QtGui

    icon = QtGui.QIcon()
    for s in (16, 22, 24, 32, 48, 64):
        icon.addPixmap(QtGui.QPixmap.fromImage(render(s, color, None, TRAY_SCALE, dot_mode)))
    return icon


def install_desktop_icons(base: Path, sizes: Iterable[int] = (16, 22, 24, 32, 48, 64, 128, 256)) -> Dict[str, Path]:
    """Значки для ярлыков в двух вариантах (белая и чёрная «C»):
    base/hicolor/<N>x<N>/apps/*.png и base/hicolor/scalable/apps/*.svg."""
    out = {}
    for black in (False, True):
        name, ring = icon_id(black), ring_color(black)
        svg_path = base / "hicolor" / "scalable" / "apps" / f"{name}.svg"
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(svg(ring=ring), encoding="utf-8")
        out[f"{name}.svg"] = svg_path
        for s in sizes:
            p = base / "hicolor" / f"{s}x{s}" / "apps" / f"{name}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            render(s, ring).save(str(p))
            out[f"{name}-{s}"] = p
    return out
