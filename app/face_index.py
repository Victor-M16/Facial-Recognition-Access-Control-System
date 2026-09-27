import threading
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select

from . import vision
from .db import ENCODED, FaceImage, Person

UNKNOWN = "Unknown"


@dataclass(frozen=True)
class Match:
    name: str
    person_id: int | None
    access_granted: bool


@dataclass(frozen=True)
class _Snapshot:
    encodings: np.ndarray      # (n, 128)
    person_ids: np.ndarray     # (n,)
    people: dict               # person_id -> (name, access_granted)


class FaceIndex:
    """In-memory copy of every encoded face, rebuilt from the database.

    Readers take the current snapshot and use it for a whole frame; reload()
    swaps in a new one, so recognition never sees a half-built index.
    """

    def __init__(self, tolerance=0.6):
        self.tolerance = tolerance
        self._lock = threading.Lock()
        self._snapshot = _Snapshot(np.empty((0, vision.ENCODING_SIZE)), np.empty(0, dtype=int), {})

    def reload(self, session):
        people = {p.id: (p.name, p.access_granted) for p in session.scalars(select(Person))}
        rows = session.execute(
            select(FaceImage.person_id, FaceImage.encoding).where(FaceImage.status == ENCODED)
        ).all()
        if rows:
            encodings = np.stack([np.frombuffer(enc, dtype=np.float64) for _, enc in rows])
            person_ids = np.array([pid for pid, _ in rows])
        else:
            encodings = np.empty((0, vision.ENCODING_SIZE))
            person_ids = np.empty(0, dtype=int)
        with self._lock:
            self._snapshot = _Snapshot(encodings, person_ids, people)

    @property
    def size(self):
        return len(self._snapshot.person_ids)

    def match(self, encoding):
        """Closest stored face wins, if it's within tolerance.

        The original supercam.py counted every stored face within tolerance as a
        vote, which favours whoever has the most photos: on the bundled dataset
        it identified all of Cliff's faces as Victor. Nearest-match gets them all.
        """
        snap = self._snapshot
        if not len(snap.person_ids):
            return Match(UNKNOWN, None, False)
        distances = np.linalg.norm(snap.encodings - encoding, axis=1)
        best = int(np.argmin(distances))
        if distances[best] > self.tolerance:
            return Match(UNKNOWN, None, False)
        person_id = int(snap.person_ids[best])
        name, access = snap.people[person_id]
        return Match(name, person_id, access)
