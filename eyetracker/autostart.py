"""Автозапуск при входе в графический сеанс (XDG autostart)."""
from __future__ import annotations

import shlex
import sys

from . import APP_NAME, paths

TEMPLATE = """[Desktop Entry]
Type=Application
Name={name}
Comment=Контроль присутствия и взгляда перед экраном
Exec={exec}
Icon=camera-web
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
"""


def exec_line() -> str:
    return f"{shlex.quote(sys.executable)} -m eyetracker"


def set_enabled(enabled: bool) -> None:
    path = paths.autostart_file()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = TEMPLATE.format(name=APP_NAME, exec=exec_line())
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    elif path.exists():
        path.unlink()
