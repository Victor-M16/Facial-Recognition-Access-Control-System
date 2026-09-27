import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import vision
from app.config import Settings
from app.main import create_app


def solid_image(value):
    """A 64x64 BGR image of one gray level. The fake encoder maps the level to an identity."""
    return np.full((64, 64, 3), value, dtype=np.uint8)


def jpeg(value):
    return vision.encode_jpeg(solid_image(value))


def fake_encode_faces(rgb, model="hog"):
    # Dark image = no face; otherwise one-hot on the brightness, so different
    # gray levels are far apart (distance sqrt(2)) and equal levels match exactly
    level = int(round(rgb.mean()))
    if level < 10:
        return []
    encoding = np.zeros(vision.ENCODING_SIZE)
    encoding[level % vision.ENCODING_SIZE] = 1.0
    return [encoding]


class FakeCamera:
    def __init__(self, frame=None):
        self.frame = frame
        self.stopped = False

    @property
    def available(self):
        return self.frame is not None

    def latest_frame(self):
        return 1, self.frame

    def wait_for_frame(self, after_id, timeout=1.0):
        return 1, self.frame

    def start(self):
        pass

    def stop(self):
        self.stopped = True


class FakeLock:
    def __init__(self):
        self.calls = []
        self.ok = True

    def lock(self):
        self.calls.append("lock")
        return self.ok

    def unlock(self):
        self.calls.append("unlock")
        return self.ok

    def status(self):
        return 1

    def close(self):
        pass


@pytest.fixture(autouse=True)
def fake_face_recognition(monkeypatch):
    monkeypatch.setattr(vision, "encode_faces", fake_encode_faces)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", database_url="")


@pytest.fixture
def camera():
    return FakeCamera(solid_image(200))


@pytest.fixture
def lock():
    return FakeLock()


@pytest.fixture
def app(settings, camera, lock):
    return create_app(settings, camera=camera, lock_client=lock, start_background=False)


@pytest.fixture
def services(app):
    return app.api.state.services


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
