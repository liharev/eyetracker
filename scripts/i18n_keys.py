#!/usr/bin/env python3
"""Список строк интерфейса, которые нужно перевести (аргументы tr(...) и таблицы с русским текстом)."""
import ast
import re
import sys
from pathlib import Path

CYR = re.compile("[А-Яа-яЁё]")

ROOT = Path(__file__).resolve().parent.parent
TABLES = {  # словари, значения которых переводятся через tr() при выводе
    "eyetracker/config.py": ["EVENT_CATEGORIES"],
    "eyetracker/policy.py": ["_STAGE_TEXT", "_LOCK_TEXT"],
    "eyetracker/sound.py": ["BUILTIN"],
}


def keys():
    out = {}
    # названия разделов справки (= вкладок окна настроек)
    from_help = ast.parse((ROOT / "eyetracker/help_content.py").read_text(encoding="utf-8"))
    for node in ast.walk(from_help):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "SECTIONS":
            for sec in node.value.elts:
                out.setdefault(sec.elts[0].value, "eyetracker/help_content.py")
    for path in sorted((ROOT / "eyetracker").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and ((isinstance(node.func, ast.Name) and node.func.id in ("tr", "N_"))
                         or (isinstance(node.func, ast.Attribute) and node.func.attr == "tr"))):
                out.setdefault(node.args[0].value, rel)
            # справка: подписи пунктов H("...") и подписи значений values={...} переводятся через tr
            if rel == "eyetracker/help_content.py" and isinstance(node, ast.Call) \
                    and isinstance(node.func, ast.Name) and node.func.id == "H":
                out.setdefault(node.args[0].value, rel)
                for kw in node.keywords:
                    if kw.arg == "values" and isinstance(kw.value, ast.Dict):
                        for v in kw.value.values:
                            if CYR.search(v.value):
                                out.setdefault(v.value, rel)
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and rel in TABLES:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id in TABLES[rel] and isinstance(node.value, ast.Dict):
                        for v in node.value.values:
                            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                                out.setdefault(v.value, rel)
    return out


if __name__ == "__main__":
    k = keys()
    for s, f in k.items():
        print(f"{f}\t{s!r}")
    print(len(k), file=sys.stderr)
