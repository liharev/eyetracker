"""Полнота и корректность перевода интерфейса."""
import ast
import re
import string
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from i18n_keys import TABLES, keys  # noqa: E402

from eyetracker import i18n  # noqa: E402
from eyetracker.i18n_en import EN  # noqa: E402

CYR = re.compile("[А-Яа-яЁё]")


def fields(s):
    return sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)


def test_every_string_translated():
    missing = [k for k in keys() if k not in EN]
    assert not missing, "нет перевода:\n" + "\n".join(missing)


def test_no_stale_translations():
    stale = sorted(set(EN) - set(keys()))
    assert not stale, "лишние переводы:\n" + "\n".join(stale)


def test_placeholders_match():
    for ru, en in EN.items():
        assert fields(ru) == fields(en), (ru, en)
        assert not CYR.search(en), en


def test_no_untranslated_ui_text():
    """Русский текст в коде — только в tr(...), таблицах, журнале (log.*), докстрингах и комментариях."""
    bad = []
    for path in sorted((ROOT / "eyetracker").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "eyetracker/i18n_en.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        ok = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                is_log = isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "log"
                is_tr = (isinstance(f, ast.Name) and f.id == "tr") or (isinstance(f, ast.Attribute) and f.attr == "tr")
                if is_log or (is_tr and node.args):
                    for sub in ast.walk(node if is_log else node.args[0]):
                        ok.add(id(sub))
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(node):
                ok.add(id(node.body[0].value))
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and rel in TABLES:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id in TABLES[rel] for t in targets):
                    for sub in ast.walk(node.value):
                        ok.add(id(sub))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and CYR.search(node.value) \
                    and id(node) not in ok:
                bad.append(f"{rel}:{node.lineno}: {node.value[:60]!r}")
    # допустимые исключения: название языка, ярлык с обоими языками, разбор «да» в настройках,
    # технические сообщения для журнала разработчика
    allowed = ("'Русский'", "autostart.py", "config.py", "resources.py", "landmarks.py")
    bad = [b for b in bad if not any(a in b for a in allowed)]
    assert not bad, "\n".join(bad)


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("ru")


def test_switching(english):
    assert i18n.app_name() == "CAMAI vigilance"
    assert i18n.tr("лиц: {n}", n=3) == "faces: 3"
    from eyetracker.config import category_title
    assert category_title("gaze") == "6. Gaze control"
    i18n.set_language("ru")
    assert i18n.app_name() == "CAMAI бдительность"
    assert i18n.tr("лиц: {n}", n=3) == "лиц: 3"


def test_system_language(monkeypatch):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    assert i18n.resolve("system") == "ru"
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.resolve("system") == "en"
    assert i18n.resolve("ru") == "ru"
