"""Добавление лица в базу авторизованных лиц: съёмка с камеры или загрузка фотографий."""
from __future__ import annotations

from typing import List, Optional

import cv2
import numpy as np

from ..qt import QtCore, QtWidgets
from ..vision.detector import face_size
from ..vision.recognizer import embedding_consistency
from .widgets import FrameView, hint

SAMPLES = 10


def _largest_face(engine, img: np.ndarray, min_size: int, require_single: bool):
    dets = engine.detector.detect(img)
    if dets.shape[0] == 0:
        return None, "Лицо не найдено"
    if require_single and dets.shape[0] > 1:
        return None, "В кадре несколько лиц — должен быть только один человек"
    row = max(dets, key=lambda r: r[2] * r[3])
    if face_size(row) < min_size:
        return None, "Лицо слишком мелкое — подойдите ближе к камере"
    return row, ""


def capture_task(engine):
    """Выполняется в потоке движка: снимок → (эмбеддинг, фото лица) или текст ошибки."""
    frame = engine.get_frame()
    if frame is None:
        return None, None, "Нет изображения с камеры"
    row, err = _largest_face(engine, frame, max(60, engine.cfg.processing.min_face_size), True)
    if row is None:
        return None, None, err
    emb = engine.embedder.embed(frame, row)
    crop = engine.embedder.align(frame, row)
    return emb, crop, ""


def file_task(paths: List[str]):
    def run(engine):
        out = []
        for p in paths:
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                out.append((p, None, None, "Не удалось открыть изображение"))
                continue
            scale = 1280.0 / max(img.shape[:2])
            if scale < 1:
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            old = engine.detector.detect_width
            engine.detector.detect_width = 0  # фотографии — в полном разрешении
            try:
                row, err = _largest_face(engine, img, 40, False)
            finally:
                engine.detector.detect_width = old
            if row is None:
                out.append((p, None, None, err))
                continue
            out.append((p, engine.embedder.embed(img, row), engine.embedder.align(img, row), ""))
        return out
    return run


class EnrollDialog(QtWidgets.QDialog):
    def __init__(self, engine, db, person_id: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.db = db
        self.person_id = person_id
        person = db.get(person_id) if person_id else None
        self.setWindowTitle("Добавление образцов: " + person.name if person else "Новое авторизованное лицо")
        self.embs: List[np.ndarray] = []
        self.photo: Optional[np.ndarray] = None
        self._capturing = False
        self._pending = None

        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit(person.name if person else "")
        self.name.setEnabled(person is None)
        form.addRow("Имя (ФИО):", self.name)
        lay.addLayout(form)
        self.view = FrameView(self)
        lay.addWidget(self.view)
        lay.addWidget(hint("Сядьте перед экраном так, как обычно работаете. Во время съёмки медленно "
                           "поворачивайте голову немного влево/вправо/вверх/вниз. В кадре должен быть "
                           "только один человек. Можно также загрузить несколько фотографий."))
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, SAMPLES)
        lay.addWidget(self.progress)
        self.msg = QtWidgets.QLabel()
        lay.addWidget(self.msg)
        row = QtWidgets.QHBoxLayout()
        self.btn_cam = QtWidgets.QPushButton(f"Снять с камеры ({SAMPLES} образцов)")
        self.btn_files = QtWidgets.QPushButton("Загрузить фото…")
        self.btn_reset = QtWidgets.QPushButton("Сбросить")
        row.addWidget(self.btn_cam)
        row.addWidget(self.btn_files)
        row.addWidget(self.btn_reset)
        lay.addLayout(row)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save
                                                  | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        lay.addWidget(self.buttons)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        self.btn_cam.clicked.connect(self._start_capture)
        self.btn_files.clicked.connect(self._from_files)
        self.btn_reset.clicked.connect(self._reset)

        self.engine.preview_enabled = True
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(150)
        self._cap_timer = QtCore.QTimer(self)
        self._cap_timer.timeout.connect(self._capture_step)
        self._update()

    def done(self, r):  # noqa: D401
        self._timer.stop()
        self._cap_timer.stop()
        super().done(r)

    def _tick(self) -> None:
        self.view.show_frame(self.engine.get_preview())
        if self._pending is not None and self._pending.done():
            fut, self._pending = self._pending, None
            try:
                emb, crop, err = fut.result()
            except Exception as exc:  # noqa: BLE001
                emb, crop, err = None, None, str(exc)
            if emb is None:
                self.msg.setText(err)
            else:
                self.embs.append(emb)
                if self.photo is None:
                    self.photo = crop
                self.msg.setText(f"Образец {len(self.embs)} снят")
            if len(self.embs) >= SAMPLES:
                self._capturing = False
                self._cap_timer.stop()
                self.msg.setText("Съёмка завершена")
            self._update()

    def _start_capture(self) -> None:
        self._capturing = True
        self._cap_timer.start(450)
        self._update()

    def _capture_step(self) -> None:
        if self._pending is None and self._capturing:
            self._pending = self.engine.submit(capture_task)

    def _from_files(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Фотографии лица", "",
                                                          "Изображения (*.jpg *.jpeg *.png *.bmp *.webp)")
        if not files:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            results = self.engine.submit(file_task(files)).result(timeout=120)
        except Exception as exc:  # noqa: BLE001
            results = []
            QtWidgets.QMessageBox.warning(self, "Ошибка", str(exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        errors = []
        for path, emb, crop, err in results:
            if emb is None:
                errors.append(f"{path}: {err}")
            else:
                self.embs.append(emb)
                if self.photo is None:
                    self.photo = crop
        if errors:
            QtWidgets.QMessageBox.warning(self, "Часть файлов не обработана", "\n".join(errors))
        self._update()

    def _reset(self) -> None:
        self.embs.clear()
        self.photo = None
        self._capturing = False
        self._cap_timer.stop()
        self.msg.clear()
        self._update()

    def _update(self) -> None:
        self.progress.setValue(min(SAMPLES, len(self.embs)))
        self.btn_cam.setEnabled(not self._capturing)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save).setEnabled(bool(self.embs)
                                                                                         and not self._capturing)

    def _save(self) -> None:
        embs = np.vstack(self.embs)
        min_sim, _ = embedding_consistency(embs)
        if min_sim < 0.25 and len(self.embs) > 1:
            if QtWidgets.QMessageBox.question(
                    self, "Проверка образцов",
                    "Образцы сильно отличаются друг от друга (возможно, в кадр попали разные люди). "
                    "Всё равно сохранить?") != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        threshold = self.engine.cfg.processing.recognition_threshold
        for emb in embs:
            m = self.db.match(emb, threshold)
            if m.person_id and m.person_id != self.person_id:
                if QtWidgets.QMessageBox.question(
                        self, "Похожее лицо уже есть",
                        f"Образцы похожи на «{m.name}» (сходство {m.score:.2f}). Всё равно сохранить?"
                ) != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
                break
        try:
            if self.person_id:
                self.db.add_samples(self.person_id, embs)
            else:
                self.db.add_person(self.name.text(), embs, self.photo)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Ошибка", str(exc))
            return
        self.accept()
