"""Thin wrappers over OpenCV and face_recognition.

The heavy libraries are imported lazily, so the rest of the app (and the tests,
which replace these functions) can load without dlib installed.
"""
import numpy as np

ENCODING_SIZE = 128


def _cv2():
    import cv2
    return cv2


def _face_recognition():
    import face_recognition
    return face_recognition


def open_camera(index):
    cv2 = _cv2()
    capture = cv2.VideoCapture(index)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return capture


def flip_vertical(frame):
    return _cv2().flip(frame, 0)


def decode_image(data):
    """Decode uploaded bytes to a BGR frame, or None if they aren't an image."""
    array = np.frombuffer(data, dtype=np.uint8)
    if array.size == 0:
        return None
    return _cv2().imdecode(array, _cv2().IMREAD_COLOR)


def encode_jpeg(frame, quality=90):
    ok, buffer = _cv2().imencode(".jpg", frame, [_cv2().IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("could not encode frame as JPEG")
    return buffer.tobytes()


def load_rgb(path):
    """Read an image file as RGB (face_recognition's channel order), or None."""
    cv2 = _cv2()
    image = cv2.imread(str(path))
    if image is None:
        return None
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def bgr_to_rgb(frame):
    cv2 = _cv2()
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def encode_faces(rgb, model="hog"):
    """Return one 128-d encoding per face found, largest face first."""
    fr = _face_recognition()
    boxes = fr.face_locations(rgb, model=model)
    # boxes are (top, right, bottom, left)
    boxes = sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]), reverse=True)
    return [np.asarray(e, dtype=np.float64) for e in fr.face_encodings(rgb, boxes)]
