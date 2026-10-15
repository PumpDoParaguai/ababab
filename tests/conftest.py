"""Never let offline tests overwrite the operator's local configuration."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    for name in ('CONFIG_FILE', 'POLICY_FILE', 'ROTATIONS_FILE', 'IMAGES_FILE'):
        monkeypatch.setattr(app, name, tmp_path / f'{name}.json')


@pytest.fixture(autouse=True)
def forbid_live_requests(monkeypatch):
    import requests
    def unexpected(*args, **kwargs):
        raise AssertionError("Unit tests must mock all external HTTP requests")
    monkeypatch.setattr(requests.Session, 'send', unexpected)
