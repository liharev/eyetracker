"""Автозапуск при входе в графический сеанс (XDG autostart)."""
from __future__ import annotations

import shlex
import sys

from . import icons, paths

TEMPLATE = """[Desktop Entry]
Type=Application
Name=CAMAI vigilance
Name[ru]=CAMAI бдительность
Comment=Presence, face recognition and gaze control in front of the screen
Comment[ru]=Контроль присутствия, распознавание лиц и контроль взгляда перед экраном
Exec={exec}
Icon={icon}
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
        content = TEMPLATE.format(exec=exec_line(), icon=icons.APP_ICON_ID)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    elif path.exists():
        path.unlink()
