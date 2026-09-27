import logging
import threading
import time

from . import vision

log = logging.getLogger(__name__)


class Camera:
    """Owns the capture device; one background thread keeps the latest frame.

    The stream and the recognizer both read latest_frame() instead of pulling
    frames from the device themselves, so extra viewers don't steal frames.
    """

    def __init__(self, index=0, flip=True):
        self.index = index
        self.flip = flip
        self._frame = None
        self._frame_id = 0
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def stopped(self):
        return self._stop.is_set()

    @property
    def available(self):
        return self._frame is not None

    def latest_frame(self):
        """Return (frame_id, frame); frame is None until the camera has produced one."""
        with self._cond:
            return self._frame_id, self._frame

    def wait_for_frame(self, after_id, timeout=1.0):
        with self._cond:
            self._cond.wait_for(lambda: self._frame_id != after_id or self._stop.is_set(), timeout)
            return self._frame_id, self._frame

    def _run(self):
        capture = None
        while not self._stop.is_set():
            if capture is None:
                capture = vision.open_camera(self.index)
                if not capture.isOpened():
                    log.warning("camera %s not available, retrying in 5s", self.index)
                    capture.release()
                    capture = None
                    self._stop.wait(5)
                    continue
            ok, frame = capture.read()
            if not ok:
                log.warning("camera read failed, reopening")
                capture.release()
                capture = None
                with self._cond:
                    self._frame = None
                time.sleep(1)
                continue
            if self.flip:
                frame = vision.flip_vertical(frame)
            with self._cond:
                self._frame = frame
                self._frame_id += 1
                self._cond.notify_all()
        if capture is not None:
            capture.release()
