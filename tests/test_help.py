"""Справка по настройкам: полнота и корректность."""
import ast
import re
from pathlib import Path

from eyetracker import i18n
from eyetracker.config import Config
from eyetracker.help_content import SECTIONS
from eyetracker.i18n_en import EN

ROOT = Path(__file__).resolve().parent.parent
CYR = re.compile("[А-Яа-яЁё]")
ITEMS = [item for sec in SECTIONS for item in sec[3]]
# псевдонимы в SettingsDialog._collect
ALIASES = {"p": "processing", "cam": "camera", "g": "gaze", "e": "email", "s": "schedule"}


def collected_settings():
    """Все параметры, которые окно настроек записывает в Config (по коду _collect)."""
    tree = ast.parse((ROOT / "eyetracker/ui/settings.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_collect")
    out = set()
    for node in ast.walk(fn):
        targets = node.targets if isinstance(node, ast.Assign) else []
        for t in targets:
            for el in (t.elts if isinstance(t, ast.Tuple) else [t]):
                if not isinstance(el, ast.Attribute):
                    continue
                v = el.value
                if isinstance(v, ast.Name) and v.id in ALIASES:
                    out.add(f"{ALIASES[v.id]}.{el.attr}")
                elif isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "c":
                    out.add(f"{v.attr}.{el.attr}")
    return out


def test_every_setting_documented():
    documented = {i.setting for i in ITEMS if i.setting}
    missing = collected_settings() - documented - {"gaze.calibrated"}   # служебное поле калибровки
    assert not missing, f"нет справки: {sorted(missing)}"


def test_settings_and_widgets_exist():
    cfg = Config()
    src = (ROOT / "eyetracker/ui/settings.py").read_text(encoding="utf-8")
    for i in ITEMS:
        if i.setting:
            section, name = i.setting.split(".")
            assert hasattr(getattr(cfg, section), name), i.setting
        if i.widget:
            assert f"self.{i.widget} = " in src, i.widget


def test_titles_translated_and_texts_complete():
    for key, intro_ru, intro_en, items in SECTIONS:
        assert key in EN and intro_ru and intro_en and not CYR.search(intro_en)
        for i in items:
            assert i.label in EN, i.label
            assert i.ru.strip() and i.en.strip() and not CYR.search(i.en), i.label
            for v in i.values.values():
                assert v in EN or not CYR.search(v) or v == "Русский", v


def test_rendering_both_languages():
    from eyetracker.ui.help import default_value, item_html, item_title
    try:
        for lang in ("ru", "en"):
            i18n.set_language(lang)
            for i in ITEMS:
                text = item_html(i)
                assert item_title(i) and text
                if lang == "en":
                    assert not CYR.search(text), text
        i18n.set_language("ru")
        t4 = next(i for i in ITEMS if i.setting == "gaze.t4_s")
        assert default_value(t4) == "60 с"
        lang = next(i for i in ITEMS if i.setting == "general.language")
        assert default_value(lang) == "Как в системе"
    finally:
        i18n.set_language("ru")
