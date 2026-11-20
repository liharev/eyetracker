"""Звуковые сигналы: 3 встроенных (генерируются при первом запуске) + загружаемые пользователем."""
from __future__ import annotations

import logging
import math
import re
import shutil
import struct
import subprocess
import threading
import wave
from pathlib import Path
from typing import List, Optional, Tuple

from . import paths
from .i18n import tr

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100
BUILTIN = {
    "beep": "Короткий сигнал (3 гудка)",
    "chime": "Двухтональный звонок",
    "siren": "Сирена",
}
ALLOWED_EXT = {".wav", ".ogg", ".oga", ".mp3", ".flac"}


def _write_wav(path: Path, samples: List[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32000)) for s in samples))


def _tone(freq: float, dur: float, vol: float = 0.6, fade: float = 0.01) -> List[float]:
    n = int(SAMPLE_RATE * dur)
    f = max(1, int(SAMPLE_RATE * fade))
    out = []
    for i in range(n):
        env = min(1.0, i / f, (n - i) / f)
        out.append(vol * env * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
    return out


def _silence(dur: float) -> List[float]:
    return [0.0] * int(SAMPLE_RATE * dur)


def _generate(name: str) -> List[float]:
    if name == "beep":
        s: List[float] = []
        for _ in range(3):
            s += _tone(1000, 0.15) + _silence(0.1)
        return s
    if name == "chime":
        decay = []
        for freq, dur in ((988, 0.35), (784, 0.6)):
            n = int(SAMPLE_RATE * dur)
            decay += [0.6 * math.exp(-3.5 * i / n) * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)
                      * min(1.0, i / 200) for i in range(n)]
        return decay
    if name == "siren":
        out, phase = [], 0.0
        dur = 1.6
        n = int(SAMPLE_RATE * dur)
        for i in range(n):
            x = i / n
            freq = 650 + 450 * (0.5 - 0.5 * math.cos(2 * math.pi * 2 * x))
            phase += 2 * math.pi * freq / SAMPLE_RATE
            env = min(1.0, i / 400, (n - i) / 400)
            out.append(0.55 * env * math.sin(phase))
        return out
    raise KeyError(name)


def builtin_dir() -> Path:
    return paths.sounds_dir() / "builtin"


def custom_dir() -> Path:
    d = paths.sounds_dir() / "custom"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_builtin_sounds() -> None:
    for name in BUILTIN:
        path = builtin_dir() / f"{name}.wav"
        if not path.exists():
            _write_wav(path, _generate(name))


def list_sounds() -> List[Tuple[str, str]]:
    """[(идентификатор, подпись)]"""
    items = [(f"builtin:{k}", tr(v)) for k, v in BUILTIN.items()]
    for p in sorted(custom_dir().iterdir()):
        if p.suffix.lower() in ALLOWED_EXT and p.is_file():
            items.append((f"custom:{p.name}", tr("Свой: {name}", name=p.name)))
    return items


def resolve(sound_id: str) -> Optional[Path]:
    kind, _, name = sound_id.partition(":")
    if kind == "builtin" and name in BUILTIN:
        ensure_builtin_sounds()
        return builtin_dir() / f"{name}.wav"
    if kind == "custom" and name and "/" not in name and name not in (".", ".."):
        p = custom_dir() / name
        return p if p.is_file() else None
    return None


def import_sound(src: Path) -> str:
    src = Path(src)
    if src.suffix.lower() not in ALLOWED_EXT:
        raise ValueError(tr("Неподдерживаемый формат. Допустимо: {formats}", formats=", ".join(sorted(ALLOWED_EXT))))
    safe = re.sub(r"[^\w.\-]+", "_", src.name, flags=re.UNICODE).strip("._") or "sound"
    if not safe.lower().endswith(src.suffix.lower()):
        safe += src.suffix.lower()
    dst = custom_dir() / safe
    shutil.copyfile(src, dst)
    return f"custom:{dst.name}"


def delete_sound(sound_id: str) -> None:
    kind, _, name = sound_id.partition(":")
    if kind != "custom":
        raise ValueError(tr("Встроенные сигналы удалить нельзя"))
    p = resolve(sound_id)
    if p:
        p.unlink()


def player_command(path: Path, volume: int) -> Optional[List[str]]:
    vol = max(0, min(100, int(volume)))
    is_wav = path.suffix.lower() == ".wav"
    if shutil.which("paplay") and (is_wav or path.suffix.lower() in (".ogg", ".oga", ".flac")):
        return ["paplay", f"--volume={int(65536 * vol / 100)}", str(path)]
    if shutil.which("pw-play"):
        return ["pw-play", f"--volume={vol / 100:.2f}", str(path)]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", str(vol), str(path)]
    if shutil.which("mpv"):
        return ["mpv", "--no-video", "--really-quiet", f"--volume={vol}", str(path)]
    if is_wav and shutil.which("aplay"):
        return ["aplay", "-q", str(path)]
    return None


class SoundPlayer:
    """Циклическое воспроизведение сигнала в фоновом потоке."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._current: Optional[Tuple[str, float, int]] = None

    @property
    def playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def looping(self) -> bool:
        """Играет циклический сигнал тревоги (а не однократное прослушивание)."""
        return self.playing and self._current is not None

    def start_loop(self, sound_id: str, repeat_s: float, volume: int) -> None:
        key = (sound_id, repeat_s, volume)
        if self.playing and self._current == key:
            return
        self.stop()
        path = resolve(sound_id) or resolve("builtin:beep")
        if path is None:
            log.error("Звуковой файл %s не найден", sound_id)
            return
        self._current = key
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(path, repeat_s, volume, True),
                                        name="sound", daemon=True)
        self._thread.start()

    def play_once(self, sound_id: str, volume: int) -> None:
        self.stop()
        path = resolve(sound_id)
        if path is None:
            return
        self._current = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(path, 0.0, volume, False),
                                        name="sound", daemon=True)
        self._thread.start()

    def _loop(self, path: Path, repeat_s: float, volume: int, loop: bool) -> None:
        cmd = player_command(path, volume)
        if cmd is None:
            log.error("Не найден проигрыватель звука (paplay / pw-play / ffplay / mpv / aplay)")
            return
        while not self._stop.is_set():
            try:
                with self._lock:
                    self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                while self._proc.poll() is None and not self._stop.is_set():
                    self._stop.wait(0.05)
            except OSError as exc:
                log.error("Ошибка воспроизведения звука: %s", exc)
                return
            finally:
                self._kill()
            if not loop:
                return
            self._stop.wait(max(0.0, repeat_s))

    def _kill(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None

    def stop(self) -> None:
        self._stop.set()
        self._kill()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None
        self._current = None
