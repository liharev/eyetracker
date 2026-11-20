"""Сбор данных самодиагностики: ресурсы одноплатника, которые использует программа.

Источники — только /proc и /sys (без сторонних библиотек и без прав root); всё, что
недоступно на конкретной системе, просто не показывается. Опрос выполняется лишь
пока открыта вкладка «Диагностика» (раз в секунду, доли миллисекунды CPU).
"""
from __future__ import annotations

import glob
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import npu, paths
from .resources import efficiency_cores

CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _read(path: str) -> Optional[str]:
    try:
        with open(path, "r") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _int(path: str) -> Optional[int]:
    v = _read(path)
    try:
        return int(v.split()[0]) if v else None
    except (ValueError, IndexError):
        return None


@dataclass
class CoreInfo:
    index: int
    load: float               # % за интервал
    freq_mhz: Optional[int]
    kind: str                 # "A55" / "A76" / ""
    allowed: bool             # разрешено ли программе


@dataclass
class Snapshot:
    t: float
    proc_cpu: float = 0.0                 # % одного ядра
    proc_cpu_total: float = 0.0           # % всех ядер
    sys_cpu: float = 0.0                  # % всех ядер
    cores: List[CoreInfo] = field(default_factory=list)
    threads: int = 0
    nice: int = 0
    rss_mb: float = 0.0
    mem_total_mb: float = 0.0
    mem_used_pct: float = 0.0
    swap_used_mb: float = 0.0
    swap_total_mb: float = 0.0
    temps: List[Tuple[str, float]] = field(default_factory=list)
    npu_available: bool = False
    npu_note: str = ""
    npu_prog_pct: float = 0.0             # доля времени NPU, занятая программой
    npu_sys_load: Optional[List[int]] = None  # загрузка ядер NPU (если доступна системой)
    npu_freq_mhz: Optional[int] = None
    npu_models: Dict[str, float] = field(default_factory=dict)  # среднее время вызова, мс
    disk_free_gb: float = 0.0
    disk_total_gb: float = 0.0
    data_mb: float = 0.0
    uptime_s: float = 0.0


class SystemMonitor:
    def __init__(self):
        self._prev_proc: Optional[Tuple[float, int]] = None
        self._prev_cores: Dict[int, Tuple[int, int]] = {}
        self._prev_npu: Optional[Tuple[float, float, Dict[str, list]]] = None
        self._data_size_t = 0.0
        self._data_mb = 0.0
        self._kinds = self._core_kinds()
        self.started = time.time()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _core_kinds() -> Dict[int, str]:
        little = set(efficiency_cores())
        out = {}
        for d in glob.glob("/sys/devices/system/cpu/cpu[0-9]*"):
            try:
                i = int(d.rsplit("cpu", 1)[1])
            except ValueError:
                continue
            out[i] = ("A55" if i in little else "A76") if little else ""
        return out

    @staticmethod
    def _proc_ticks() -> Optional[int]:
        st = _read("/proc/self/stat")
        if not st:
            return None
        f = st.rsplit(")", 1)[1].split()
        return int(f[11]) + int(f[12])   # utime + stime (включая все потоки)

    @staticmethod
    def _cpu_times() -> Dict[int, Tuple[int, int]]:
        out = {}
        txt = _read("/proc/stat") or ""
        for line in txt.splitlines():
            if line.startswith("cpu") and line[3:4].isdigit():
                parts = line.split()
                vals = [int(v) for v in parts[1:]]
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                out[int(parts[0][3:])] = (sum(vals), idle)
        return out

    @staticmethod
    def _meminfo() -> Dict[str, int]:
        out = {}
        for line in (_read("/proc/meminfo") or "").splitlines():
            k, _, v = line.partition(":")
            try:
                out[k] = int(v.split()[0])
            except (ValueError, IndexError):
                pass
        return out

    @staticmethod
    def _temps() -> List[Tuple[str, float]]:
        out = []
        for d in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            name = _read(d + "/type") or os.path.basename(d)
            t = _int(d + "/temp")
            if t is not None and t > 0:
                out.append((name.replace("-thermal", "").replace("_thermal", ""), t / 1000.0))
        return out

    @staticmethod
    def _npu_system() -> Tuple[Optional[List[int]], Optional[int]]:
        load = None
        txt = _read("/sys/kernel/debug/rknpu/load")      # обычно доступно только root
        if txt and "%" in txt:
            load = [int(x.split("%")[0].split()[-1]) for x in txt.split(",") if "%" in x]
        freq = None
        for d in glob.glob("/sys/class/devfreq/*npu*"):
            f = _int(d + "/cur_freq")
            if f:
                freq = f // 1_000_000
            if load is None:
                v = _read(d + "/load")
                if v and "@" in v:
                    try:
                        load = [int(v.split("@")[0])]
                    except ValueError:
                        pass
        return load, freq

    def _data_size(self) -> float:
        now = time.time()
        if now - self._data_size_t > 30:
            total = 0
            for root, _, files in os.walk(paths.data_dir()):
                if "/venv" in root or root.endswith("venv"):
                    continue
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            self._data_mb = total / 1e6
            self._data_size_t = now
        return self._data_mb

    # -------------------------------------------------------------- sample
    def sample(self) -> Snapshot:
        now = time.monotonic()
        s = Snapshot(t=now)
        ncpu = os.cpu_count() or 1

        ticks = self._proc_ticks()
        if ticks is not None and self._prev_proc:
            dt = now - self._prev_proc[0]
            if dt > 0:
                s.proc_cpu = (ticks - self._prev_proc[1]) / CLK_TCK / dt * 100
                s.proc_cpu_total = s.proc_cpu / ncpu
        if ticks is not None:
            self._prev_proc = (now, ticks)

        times = self._cpu_times()
        try:
            allowed = os.sched_getaffinity(0)
        except (AttributeError, OSError):
            allowed = set(times)
        busy_sum = total_sum = 0
        for i, (tot, idle) in sorted(times.items()):
            load = 0.0
            if i in self._prev_cores:
                dtot = tot - self._prev_cores[i][0]
                didle = idle - self._prev_cores[i][1]
                if dtot > 0:
                    load = 100.0 * (dtot - didle) / dtot
                    busy_sum += dtot - didle
                    total_sum += dtot
            freq = _int(f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq")
            s.cores.append(CoreInfo(i, load, freq // 1000 if freq else None, self._kinds.get(i, ""), i in allowed))
        self._prev_cores = times
        s.sys_cpu = 100.0 * busy_sum / total_sum if total_sum else 0.0

        status = _read("/proc/self/status") or ""
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                s.rss_mb = int(line.split()[1]) / 1024
            elif line.startswith("Threads:"):
                s.threads = int(line.split()[1])
        try:
            s.nice = os.nice(0)
        except OSError:
            pass
        mi = self._meminfo()
        if mi.get("MemTotal"):
            s.mem_total_mb = mi["MemTotal"] / 1024
            s.mem_used_pct = 100.0 * (mi["MemTotal"] - mi.get("MemAvailable", mi.get("MemFree", 0))) / mi["MemTotal"]
        s.swap_total_mb = mi.get("SwapTotal", 0) / 1024
        s.swap_used_mb = (mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)) / 1024

        s.temps = self._temps()

        s.npu_available, s.npu_note = npu.availability() if npu.device_present() else (False, "")
        busy = npu.STATS["busy_s"]
        models = {k: list(v) for k, v in npu.STATS["models"].items()}
        if self._prev_npu:
            dt = now - self._prev_npu[0]
            if dt > 0:
                s.npu_prog_pct = min(100.0, 100.0 * (busy - self._prev_npu[1]) / dt)
            for name, (n, tsum) in models.items():
                pn, pt = self._prev_npu[2].get(name, [0, 0.0])
                if n > pn:
                    s.npu_models[name] = (tsum - pt) / (n - pn) * 1000
        self._prev_npu = (now, busy, models)
        s.npu_sys_load, s.npu_freq_mhz = self._npu_system()

        try:
            du = shutil.disk_usage(paths.data_dir())
            s.disk_free_gb, s.disk_total_gb = du.free / 1e9, du.total / 1e9
        except OSError:
            pass
        s.data_mb = self._data_size()
        s.uptime_s = time.time() - self.started
        return s


# Пороговые значения цвета: (жёлтый с, красный с); для «чем больше, тем лучше» — reverse.
LEVELS = {
    "proc_cpu": (25.0, 50.0),        # % одного ядра
    "sys_cpu": (60.0, 85.0),
    "core": (70.0, 90.0),
    "rss_mb": (400.0, 800.0),
    "mem_pct": (75.0, 90.0),
    "swap_pct": (25.0, 60.0),
    "temp": (70.0, 85.0),
    "npu": (40.0, 75.0),
    "proc_ms": (100.0, 180.0),       # время обработки кадра при 5 кадр/с (бюджет 200 мс)
    "disk_free_pct": (15.0, 5.0),    # reverse
}


def level(kind: str, value: float) -> int:
    """0 — норма (зелёный), 1 — повышенная нагрузка (жёлтый), 2 — высокая (красный)."""
    warn, crit = LEVELS[kind]
    if warn > crit:      # чем меньше, тем хуже
        return 2 if value <= crit else 1 if value <= warn else 0
    return 2 if value >= crit else 1 if value >= warn else 0
