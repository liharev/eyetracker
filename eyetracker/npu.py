"""Запуск моделей на NPU Rockchip RK3588 через C-интерфейс librknnrt.so (ctypes).

Python-пакет rknn-toolkit-lite2 выпускается не для всех версий Python (например, для 3.14
его нет), поэтому библиотека выполнения вызывается напрямую — так работает с любым Python.
Структуры повторяют rknn_api.h (rknn-toolkit2 v2.5.0, aarch64).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import threading
from pathlib import Path
from typing import List, Sequence

import numpy as np

from . import paths

log = logging.getLogger(__name__)

RKNN_SUCC = 0
RKNN_MAX_DIMS = 16
RKNN_MAX_NAME_LEN = 256
RKNN_QUERY_IN_OUT_NUM = 0
RKNN_QUERY_INPUT_ATTR = 1
RKNN_QUERY_OUTPUT_ATTR = 2
RKNN_QUERY_SDK_VERSION = 5
RKNN_TENSOR_UINT8 = 3
RKNN_TENSOR_NHWC = 1
RKNN_FLAG_PRIOR_LOW = 0x2
CORE_MASKS = {"auto": 0, "0": 1, "1": 2, "2": 4, "0_1": 3, "0_1_2": 7, "all": 0xFFFF}

rknn_context = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class _InOutNum(ctypes.Structure):
    _fields_ = [("n_input", ctypes.c_uint32), ("n_output", ctypes.c_uint32)]


class _TensorAttr(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("n_dims", ctypes.c_uint32),
        ("dims", ctypes.c_uint32 * RKNN_MAX_DIMS),
        ("name", ctypes.c_char * RKNN_MAX_NAME_LEN),
        ("n_elems", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("fmt", ctypes.c_int),
        ("type", ctypes.c_int),
        ("qnt_type", ctypes.c_int),
        ("fl", ctypes.c_int8),
        ("zp", ctypes.c_int32),
        ("scale", ctypes.c_float),
        ("w_stride", ctypes.c_uint32),
        ("size_with_stride", ctypes.c_uint32),
        ("pass_through", ctypes.c_uint8),
        ("h_stride", ctypes.c_uint32),
    ]


class _Input(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("buf", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
        ("pass_through", ctypes.c_uint8),
        ("type", ctypes.c_int),
        ("fmt", ctypes.c_int),
    ]


class _Output(ctypes.Structure):
    _fields_ = [
        ("want_float", ctypes.c_uint8),
        ("is_prealloc", ctypes.c_uint8),
        ("index", ctypes.c_uint32),
        ("buf", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
    ]


class _SdkVersion(ctypes.Structure):
    _fields_ = [("api_version", ctypes.c_char * 256), ("drv_version", ctypes.c_char * 256)]


class NpuError(RuntimeError):
    pass


def library_paths() -> List[Path]:
    cands = []
    env = os.environ.get("EYETRACKER_RKNNRT")
    if env:
        cands.append(Path(env))
    cands += [
        paths.data_dir() / "lib" / "librknnrt.so",
        Path("/usr/lib/librknnrt.so"),
        Path("/usr/lib/aarch64-linux-gnu/librknnrt.so"),
        Path("/usr/local/lib/librknnrt.so"),
    ]
    found = ctypes.util.find_library("rknnrt")
    if found:
        cands.append(Path(found))
    return cands


_lib = None
_lib_lock = threading.Lock()
_lib_error = ""


def load_library():
    """Загружает librknnrt.so; при неудаче — NpuError с понятным описанием."""
    global _lib, _lib_error
    with _lib_lock:
        if _lib is not None:
            return _lib
        if os.uname().machine not in ("aarch64", "arm64"):
            _lib_error = "NPU Rockchip доступен только на ARM64 (RK3588)"
            raise NpuError(_lib_error)
        errors = []
        for p in library_paths():
            if not p.exists() and "/" in str(p):
                continue
            try:
                lib = ctypes.CDLL(str(p))
            except OSError as exc:
                errors.append(f"{p}: {exc}")
                continue
            _declare(lib)
            _lib = lib
            log.info("NPU: библиотека %s", p)
            return lib
        _lib_error = "не найдена librknnrt.so (её устанавливает install.sh)" + (
            "; " + "; ".join(errors) if errors else "")
        raise NpuError(_lib_error)


def _declare(lib) -> None:
    ctx_p = ctypes.POINTER(rknn_context)
    lib.rknn_init.argtypes = [ctx_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    lib.rknn_destroy.argtypes = [rknn_context]
    lib.rknn_query.argtypes = [rknn_context, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.rknn_inputs_set.argtypes = [rknn_context, ctypes.c_uint32, ctypes.POINTER(_Input)]
    lib.rknn_run.argtypes = [rknn_context, ctypes.c_void_p]
    lib.rknn_outputs_get.argtypes = [rknn_context, ctypes.c_uint32, ctypes.POINTER(_Output), ctypes.c_void_p]
    lib.rknn_outputs_release.argtypes = [rknn_context, ctypes.c_uint32, ctypes.POINTER(_Output)]
    lib.rknn_set_core_mask.argtypes = [rknn_context, ctypes.c_int]
    for fn in ("rknn_init", "rknn_destroy", "rknn_query", "rknn_inputs_set", "rknn_run", "rknn_outputs_get",
               "rknn_outputs_release", "rknn_set_core_mask"):
        getattr(lib, fn).restype = ctypes.c_int


def _check(ret: int, what: str) -> None:
    if ret != RKNN_SUCC:
        raise NpuError(f"{what}: код ошибки {ret}")


def device_present() -> bool:
    """Есть ли в системе устройство NPU (драйвер rknpu)."""
    if Path("/dev/rknpu").exists():
        return True
    for p in Path("/sys/class/drm").glob("*/device/driver"):
        try:
            if "rknpu" in os.readlink(p):
                return True
        except OSError:
            pass
    return Path("/sys/module/rknpu").exists() or Path("/proc/device-tree/npu@fdab0000").exists()


class RknnModel:
    """Модель .rknn: вход — uint8 NHWC (нормализация встроена в модель), выход — float32."""

    def __init__(self, model_path: Path, core: str = "auto", low_priority: bool = True):
        self.lib = load_library()
        self.path = Path(model_path)
        data = self.path.read_bytes()
        self._buf = ctypes.create_string_buffer(data, len(data))
        self.ctx = rknn_context(0)
        flag = RKNN_FLAG_PRIOR_LOW if low_priority else 0
        _check(self.lib.rknn_init(ctypes.byref(self.ctx), ctypes.cast(self._buf, ctypes.c_void_p), len(data),
                                  flag, None), f"rknn_init({self.path.name})")
        del self._buf  # после init модель скопирована во внутреннюю память
        try:
            mask = CORE_MASKS.get(str(core), 0)
            if mask:
                _check(self.lib.rknn_set_core_mask(self.ctx, mask), "rknn_set_core_mask")
            num = _InOutNum()
            _check(self.lib.rknn_query(self.ctx, RKNN_QUERY_IN_OUT_NUM, ctypes.byref(num), ctypes.sizeof(num)),
                   "rknn_query(IN_OUT_NUM)")
            self.inputs = [self._attr(RKNN_QUERY_INPUT_ATTR, i) for i in range(num.n_input)]
            self.outputs = [self._attr(RKNN_QUERY_OUTPUT_ATTR, i) for i in range(num.n_output)]
        except Exception:
            self.close()
            raise
        self.output_names = [a.name.decode(errors="replace") for a in self.outputs]
        self._out_bufs = [np.empty(int(a.n_elems), np.float32) for a in self.outputs]
        self._outs = (_Output * len(self.outputs))()
        for i, buf in enumerate(self._out_bufs):
            self._outs[i].want_float = 1
            self._outs[i].is_prealloc = 1
            self._outs[i].index = i
            self._outs[i].buf = buf.ctypes.data
            self._outs[i].size = buf.nbytes

    def _attr(self, cmd: int, i: int) -> _TensorAttr:
        a = _TensorAttr()
        a.index = i
        _check(self.lib.rknn_query(self.ctx, cmd, ctypes.byref(a), ctypes.sizeof(a)), "rknn_query(ATTR)")
        return a

    def input_shape(self, i: int = 0) -> tuple:
        a = self.inputs[i]
        return tuple(int(a.dims[k]) for k in range(a.n_dims))

    def run(self, images: Sequence[np.ndarray]) -> List[np.ndarray]:
        """images — uint8 HxWxC (NHWC без размерности пакета). Возвращает копии выходов."""
        arrays = [np.ascontiguousarray(img, dtype=np.uint8) for img in images]
        ins = (_Input * len(arrays))()
        for i, arr in enumerate(arrays):
            ins[i].index = i
            ins[i].buf = arr.ctypes.data
            ins[i].size = arr.nbytes
            ins[i].pass_through = 0
            ins[i].type = RKNN_TENSOR_UINT8
            ins[i].fmt = RKNN_TENSOR_NHWC
        _check(self.lib.rknn_inputs_set(self.ctx, len(arrays), ins), "rknn_inputs_set")
        _check(self.lib.rknn_run(self.ctx, None), "rknn_run")
        _check(self.lib.rknn_outputs_get(self.ctx, len(self._out_bufs), self._outs, None), "rknn_outputs_get")
        try:
            return [b.copy() for b in self._out_bufs]
        finally:
            self.lib.rknn_outputs_release(self.ctx, len(self._out_bufs), self._outs)

    def run_named(self, images: Sequence[np.ndarray]) -> dict:
        return dict(zip(self.output_names, self.run(images)))

    def sdk_version(self) -> tuple:
        v = _SdkVersion()
        if self.lib.rknn_query(self.ctx, RKNN_QUERY_SDK_VERSION, ctypes.byref(v), ctypes.sizeof(v)) == RKNN_SUCC:
            return v.api_version.decode(errors="replace"), v.drv_version.decode(errors="replace")
        return "?", "?"

    def close(self) -> None:
        if getattr(self, "ctx", None) is not None and self.ctx.value:
            self.lib.rknn_destroy(self.ctx)
            self.ctx = rknn_context(0)

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass


def availability() -> tuple:
    """(доступен ли NPU, пояснение) — для самопроверки и выбора ускорителя."""
    if os.uname().machine not in ("aarch64", "arm64"):
        return False, "не ARM64 — NPU Rockchip недоступен"
    if not device_present():
        return False, "устройство NPU (драйвер rknpu) не найдено"
    try:
        load_library()
    except NpuError as exc:
        return False, str(exc)
    return True, "готов"


def last_error() -> str:
    return _lib_error

