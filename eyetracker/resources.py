"""Ограничение потребления ресурсов: потоки, приоритет, привязка к ядрам CPU.

На RK3588 (Radxa ROCK 5T) 4 ядра Cortex-A55 (cpu0-3) и 4 ядра Cortex-A76 (cpu4-7).
По умолчанию утилита работает только на «малых» ядрах A55 с пониженным приоритетом,
оставляя производительные ядра A76 прикладному ПО.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional, Set

log = logging.getLogger(__name__)

# Переменные окружения для библиотек, читающих их при импорте
# (вызывать limit_threads_env() до импорта numpy / cv2 / mediapipe).
_THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def limit_threads_env(n: int = 1) -> None:
    for var in _THREAD_ENV:
        os.environ.setdefault(var, str(n))
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    os.environ.setdefault("GLOG_minloglevel", "2")


def parse_cpu_list(text: str) -> Set[int]:
    cpus: Set[int] = set()
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            cpus.update(range(int(a), int(b) + 1))
        else:
            cpus.add(int(part))
    return cpus


def _read_int(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def efficiency_cores(sys_cpu: Path = Path("/sys/devices/system/cpu")) -> List[int]:
    """Ядра с наименьшей производительностью (cpu_capacity или макс. частота).
    Пустой список — система однородная, ограничение не требуется."""
    perf = {}
    for d in sorted(sys_cpu.glob("cpu[0-9]*")):
        try:
            idx = int(d.name[3:])
        except ValueError:
            continue
        val = _read_int(d / "cpu_capacity") or _read_int(d / "cpufreq" / "cpuinfo_max_freq")
        if val:
            perf[idx] = val
    if len(set(perf.values())) < 2:
        return []
    low = min(perf.values())
    return sorted(i for i, v in perf.items() if v == low)


def apply_limits(cpu_cores: str = "auto", nice: int = 10) -> str:
    """Применяет ограничения к текущему процессу; возвращает описание для журнала."""
    notes = []
    try:
        import cv2

        cv2.setNumThreads(1)
        notes.append("OpenCV: 1 поток")
    except Exception:  # noqa: BLE001
        pass
    if nice > 0:
        try:
            cur = os.nice(0)
            if cur < nice:
                os.nice(nice - cur)
            notes.append(f"nice={os.nice(0)}")
        except OSError as exc:
            log.debug("nice: %s", exc)
    spec = (cpu_cores or "").strip().lower()
    if spec and hasattr(os, "sched_setaffinity"):
        try:
            cores = efficiency_cores() if spec == "auto" else sorted(parse_cpu_list(spec))
            available = os.sched_getaffinity(0)
            cores = [c for c in cores if c in available]
            if cores:
                os.sched_setaffinity(0, cores)
                notes.append("ядра CPU: " + ",".join(map(str, cores)))
        except (OSError, ValueError) as exc:
            log.warning("Не удалось ограничить ядра CPU (%s): %s", cpu_cores, exc)
    summary = "; ".join(notes)
    log.info("Ограничение ресурсов: %s", summary or "нет")
    return summary
