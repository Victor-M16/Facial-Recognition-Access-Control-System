import pytest

from app.face_index import UNKNOWN, Match
from app.recognizer import Recognizer
from conftest import solid_image

ALICE = Match("Alice", 1, True)
PEMPHERO = Match("Pemphero", 2, False)
STRANGER = Match(UNKNOWN, None, False)


class FakeAccess:
    def __init__(self):
        self.calls = []

    def lock(self, name=None, source="remote"):
        self.calls.append(("lock", name))

    def unlock(self, name=None, source="remote"):
        self.calls.append(("unlock", name))


@pytest.fixture
def access():
    return FakeAccess()


@pytest.fixture
def notified():
    return []


@pytest.fixture
def recognizer(access, notified):
    return Recognizer(camera=None, index=None, access=access, notify=notified.append)


def test_granted_unlocks_and_denied_or_unknown_locks(recognizer, access, notified):
    recognizer.handle(ALICE)
    recognizer.handle(PEMPHERO)
    recognizer.handle(STRANGER)
    assert access.calls == [("unlock", "Alice"), ("lock", "Pemphero"), ("lock", UNKNOWN)]
    assert notified == ["Alice", "Pemphero", UNKNOWN]


def test_same_person_only_acts_once_until_reset(recognizer, access):
    recognizer.handle(ALICE)
    recognizer.handle(ALICE)
    assert access.calls == [("unlock", "Alice")]
    recognizer.reset()
    recognizer.handle(ALICE)
    assert len(access.calls) == 2


def test_anyone_unauthorized_in_frame_keeps_door_locked(recognizer, access):
    class Index:
        def __init__(self, matches):
            self.matches = iter(matches)

        def match(self, encoding):
            return next(self.matches)

    import app.vision as vision
    original = vision.encode_faces
    vision.encode_faces = lambda rgb, model="hog": [0, 1]
    try:
        recognizer.index = Index([ALICE, STRANGER])
        recognizer.process(solid_image(100))
    finally:
        vision.encode_faces = original
    assert access.calls == [("lock", UNKNOWN)]


def test_nearest_face_wins_over_the_person_with_more_photos():
    import numpy as np
    from app.face_index import FaceIndex, _Snapshot

    index = FaceIndex(tolerance=0.6)
    # Victor has three photos 0.5 away from the probe, Cliff one photo 0.1 away:
    # vote counting said Victor, nearest-match says Cliff
    probe = np.zeros(128)
    victor = np.zeros((3, 128))
    victor[:, 0] = 0.5
    cliff = np.zeros((1, 128))
    cliff[0, 1] = 0.1
    index._snapshot = _Snapshot(np.vstack([victor, cliff]), np.array([1, 1, 1, 2]),
                                {1: ("Victor", True), 2: ("Cliff", True)})
    assert index.match(probe).name == "Cliff"

    far = np.zeros(128)
    far[5] = 1.0
    assert index.match(far).name == UNKNOWN
