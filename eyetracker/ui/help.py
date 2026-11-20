"""Вкладка «Помощь»: описание каждого параметра настроек, поиск, подсказки и F1."""
from __future__ import annotations

import html
from typing import Dict, List, Optional

from ..config import Config
from ..help_content import SECTIONS, HelpItem
from ..i18n import app_name, language, tr
from ..qt import Qt, QtWidgets


# ---------------------------------------------------------------- тексты
def item_title(item: HelpItem) -> str:
    suffix = item.suffix_en if language() == "en" else item.suffix_ru
    return tr(item.label).rstrip(":").strip() + suffix


def item_description(item: HelpItem) -> str:
    return item.en if language() == "en" else item.ru


def default_value(item: HelpItem) -> Optional[str]:
    """Значение по умолчанию — из Config(), т.е. ровно то, что задано в программе."""
    if not item.setting:
        return None
    obj = Config()
    for part in item.setting.split("."):
        obj = getattr(obj, part)
    if isinstance(obj, bool):
        return tr("включено") if obj else tr("выключено")
    if isinstance(obj, str) and obj in item.values:
        return tr(item.values[obj])
    if isinstance(obj, (int, float)):
        return f"{obj:g}{tr(item.unit) if item.unit else ''}"
    return obj if obj else tr("не задано")


def item_html(item: HelpItem, level: int = 3) -> str:
    out = [f"<h{level}>{html.escape(item_title(item))}</h{level}>",
           f"<p>{html.escape(item_description(item))}</p>"]
    d = default_value(item)
    if d is not None:
        out.append(f"<p style='color:#666'><i>{html.escape(tr('По умолчанию: {value}', value=d))}</i></p>")
    return "\n".join(out)


def item_tooltip(item: HelpItem) -> str:
    """Подсказка при наведении (rich text — Qt переносит строки)."""
    d = default_value(item)
    tip = f"<b>{html.escape(item_title(item))}</b><br>{html.escape(item_description(item))}"
    if d is not None:
        tip += f"<br><i>{html.escape(tr('По умолчанию: {value}', value=d))}</i>"
    return f"<div style='max-width:420px'>{tip}</div>"


def section_intro(sec) -> str:
    return sec[2] if language() == "en" else sec[1]


# ---------------------------------------------------------------- вкладка
class HelpTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(tr("Поиск по настройкам…"))
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.view = QtWidgets.QTextBrowser()
        self.view.setOpenExternalLinks(False)
        split.addWidget(self.tree)
        split.addWidget(self.view)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([330, 570])
        lay.addWidget(split, 1)

        self._sections: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        for sec in SECTIONS:
            top = QtWidgets.QTreeWidgetItem([tr(sec[0])])
            top.setData(0, Qt.ItemDataRole.UserRole, ("section", sec))
            for item in sec[3]:
                child = QtWidgets.QTreeWidgetItem([item_title(item)])
                child.setData(0, Qt.ItemDataRole.UserRole, ("item", item))
                child.setToolTip(0, item_title(item))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            self._sections[sec[0]] = top
        self.tree.currentItemChanged.connect(self._show)
        self.search.textChanged.connect(self._filter)
        self._overview()

    def _overview(self) -> None:
        intro = tr("Выберите раздел или параметр слева либо воспользуйтесь поиском. Подсказка по любому "
                   "параметру появляется и при наведении на него мыши, а клавиша F1 открывает справку по "
                   "текущей вкладке.")
        parts = [f"<h2>{html.escape(tr('Помощь'))} — {html.escape(app_name())}</h2>",
                 f"<p>{html.escape(intro)}</p><ul>"]
        for sec in SECTIONS:
            parts.append(f"<li><b>{html.escape(tr(sec[0]))}</b> — {html.escape(section_intro(sec))}</li>")
        parts.append("</ul>")
        self.view.setHtml("".join(parts))

    def _show(self, cur, _prev=None) -> None:
        if cur is None:
            self._overview()
            return
        kind, data = cur.data(0, Qt.ItemDataRole.UserRole)
        if kind == "item":
            self.view.setHtml(item_html(data, 2))
            return
        parts = [f"<h2>{html.escape(tr(data[0]))}</h2><p>{html.escape(section_intro(data))}</p><hr>"]
        parts += [item_html(i) for i in data[3]]
        self.view.setHtml("".join(parts))

    def _filter(self, text: str) -> None:
        q = text.strip().lower()
        first = first_title = None
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            sec_match = q in top.text(0).lower() if q else True
            any_child = False
            for j in range(top.childCount()):
                ch = top.child(j)
                item = ch.data(0, Qt.ItemDataRole.UserRole)[1]
                match = not q or sec_match or q in ch.text(0).lower() or q in item_description(item).lower()
                ch.setHidden(not match)
                if match and q and first is None:
                    first = ch
                if match and q and first_title is None and q in ch.text(0).lower():
                    first_title = ch           # совпадение в названии — показываем в первую очередь
                any_child |= match
            top.setHidden(not (any_child or sec_match))
            top.setExpanded(bool(q) and any_child)
        if q and first is not None:
            self.tree.setCurrentItem(first_title or first)
        elif q:
            self.view.setHtml(f"<p>{html.escape(tr('Ничего не найдено'))}</p>")
        else:
            self.tree.setCurrentItem(None)
            self._overview()

    def show_section(self, key: str) -> None:
        top = self._sections.get(key)
        if top is not None:
            self.search.clear()
            top.setExpanded(True)
            self.tree.setCurrentItem(top)


def apply_tooltips(dialog) -> List[str]:
    """Подсказки к элементам окна настроек и их подписям; возвращает элементы без подсказки."""
    missing = []
    layouts = dialog.findChildren(QtWidgets.QFormLayout)
    for sec in SECTIONS:
        for item in sec[3]:
            if not item.widget:
                continue
            w = getattr(dialog, item.widget, None)
            if w is None:
                missing.append(item.widget)
                continue
            tip = item_tooltip(item)
            w.setToolTip(tip)
            for lay in layouts:
                label = lay.labelForField(w)
                if label is not None:
                    label.setToolTip(tip)
                    break
    return missing
