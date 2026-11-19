import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("EYETRACKER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("EYETRACKER_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path


def models_dir():
    env = os.environ.get("EYETRACKER_MODELS")
    return Path(env) if env else None
