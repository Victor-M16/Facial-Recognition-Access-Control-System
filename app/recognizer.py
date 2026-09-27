import logging
import threading
import time

from . import vision

log = logging.getLogger(__name__)


class Recognizer:
    """Background thread that watches the camera and drives the lock.

    It runs whether or not anyone is viewing the stream. Training pauses it so
    the Pi's CPU goes to encoding.
    """

    def __init__(self, camera, index, access, notify, detection_model="hog", forget_after=5.0,
                 clock=time.monotonic):
        self.camera = camera
        self.index = index
        self.access = access
        self.notify = notify
        self.detection_model = detection_model
        self.forget_after = forget_after
        self.clock = clock
        self.current = None
        self.last_seen = 0.0
        self._paused = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="recognizer", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def pause(self):
        self._paused.set()

    def resume(self):
        self._paused.clear()

    def reset(self):
        # Forget who was last in view, so the next frame is re-evaluated against
        # changed access rules or a retrained index
        self.current = None

    @property
    def paused(self):
        return self._paused.is_set()

    def _run(self):
        last_id = 0
        while not self._stop.is_set():
            if self._paused.is_set():
                self._stop.wait(0.5)
                continue
            frame_id, frame = self.camera.wait_for_frame(last_id, timeout=1.0)
            if frame is None or frame_id == last_id:
                continue
            last_id = frame_id
            try:
                self.process(frame)
            except Exception:
                log.exception("recognition failed on a frame")

    def process(self, frame):
        rgb = vision.bgr_to_rgb(frame)
        matches = [self.index.match(e) for e in vision.encode_faces(rgb, self.detection_model)]
        now = self.clock()
        if not matches:
            # The ESP32 relocks by itself shortly after an unlock. Once nobody has been in
            # view for a while, forget who was there, so they're let in again when they return
            if self.current is not None and now - self.last_seen >= self.forget_after:
                self.current = None
            return
        self.last_seen = now
        # If anyone in view is unknown or denied, that decides the frame, so a
        # granted face can't hold the door open for someone else
        denied = [m for m in matches if not m.access_granted]
        self.handle(denied[0] if denied else matches[0])

    def handle(self, match):
        # Only act when the person in view changes, so the servo isn't hammered every frame
        if match.name == self.current:
            return
        self.current = match.name
        if match.distance is not None:
            # Distances seen at the door are what FRACS_MATCH_TOLERANCE should be tuned against
            log.info("%s in view (closest enrolled face %.3f away)", match.name, match.distance)
        self.notify(match.name)
        if match.access_granted:
            self.access.unlock(match.name, source="face")
        else:
            self.access.lock(match.name, source="face")
