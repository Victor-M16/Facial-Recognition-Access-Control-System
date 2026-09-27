import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm.exc import StaleDataError

from . import vision
from .db import ENCODED, FAILED, NO_FACE, PENDING, FaceImage

log = logging.getLogger(__name__)


class Trainer:
    """Encodes enrolled images on a background thread, one run at a time.

    A normal run only encodes images still marked pending, so adding a person
    doesn't re-process everyone else. full=True re-encodes every image.
    Each image is committed as it's done, so an interrupted run loses nothing.
    """

    def __init__(self, session_factory, settings, index, on_progress, on_start=None, on_finish=None):
        self.session_factory = session_factory
        self.settings = settings
        self.index = index
        self.on_progress = on_progress
        self.on_start = on_start or (lambda: None)
        self.on_finish = on_finish or (lambda: None)
        self._lock = threading.Lock()
        self._thread = None
        self._status = {"state": "idle", "done": 0, "total": 0, "message": "Not trained yet",
                        "encoded": 0, "no_face": 0, "failed": 0, "full": False,
                        "started_at": None, "finished_at": None}

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def status(self):
        with self._lock:
            return dict(self._status)

    def start(self, full=False):
        """Start a run; returns False if one is already in progress."""
        with self._lock:
            if self.running:
                return False
            self._status.update(state="running", done=0, total=0, encoded=0, no_face=0, failed=0,
                                full=full, message="Starting training...",
                                started_at=_now(), finished_at=None)
            self._thread = threading.Thread(target=self._run, args=(full,), name="trainer", daemon=True)
            self._thread.start()
        return True

    def wait(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    def _set(self, **changes):
        with self._lock:
            self._status.update(changes)
            snapshot = dict(self._status)
        self.on_progress(snapshot)

    def _run(self, full):
        self.on_start()
        try:
            with self.session_factory() as session:
                if full:
                    session.execute(update(FaceImage).values(status=PENDING, encoding=None))
                    session.commit()
                ids = session.scalars(
                    select(FaceImage.id).where(FaceImage.status == PENDING).order_by(FaceImage.id)
                ).all()
                total = len(ids)
                self._set(total=total, message=f"Processing {total} new image(s)..." if total
                          else "No new images to train on")
                counts = {ENCODED: 0, NO_FACE: 0, FAILED: 0}
                for n, image_id in enumerate(ids, start=1):
                    image = session.get(FaceImage, image_id)
                    if image is None:  # deleted while training
                        continue
                    status, encoding = self._encode(image)
                    image.status, image.encoding = status, encoding
                    try:
                        session.commit()
                    except StaleDataError:  # deleted while we were encoding it
                        session.rollback()
                        continue
                    counts[status] += 1
                    self._set(done=n, encoded=counts[ENCODED], no_face=counts[NO_FACE],
                              failed=counts[FAILED], message=f"Processing image {n}/{total}")
                self.index.reload(session)
            if not total:
                self._set(state="done", message="Nothing new to train on. Capture or upload photos first.",
                          finished_at=_now())
                return
            message = f"Training complete: {counts[ENCODED]} encoded"
            if counts[NO_FACE]:
                message += f", {counts[NO_FACE]} with no face found"
            if counts[FAILED]:
                message += f", {counts[FAILED]} unreadable"
            self._set(state="done", message=message, finished_at=_now())
        except Exception as exc:
            log.exception("training failed")
            self._set(state="failed", message=f"Training failed: {exc}", finished_at=_now())
        finally:
            self.on_finish()

    def _encode(self, image):
        rgb = vision.load_rgb(self.settings.data_dir / image.path)
        if rgb is None:
            return FAILED, None
        encodings = vision.encode_faces(rgb, self.settings.detection_model)
        if not encodings:
            return NO_FACE, None
        # Enrollment photos should show one person; if there are more, keep the largest face
        return ENCODED, encodings[0].astype("float64").tobytes()


def _now():
    return datetime.now(timezone.utc).isoformat()
