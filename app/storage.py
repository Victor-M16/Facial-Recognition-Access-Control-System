import shutil
import uuid

from . import vision


def save_face_image(settings, person_id, frame):
    """Write a BGR frame as JPEG under data_dir; returns the path relative to data_dir."""
    relative = f"faces/{person_id}/{uuid.uuid4().hex}.jpg"
    path = settings.data_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(vision.encode_jpeg(frame))
    return relative


def delete_face_image(settings, relative):
    (settings.data_dir / relative).unlink(missing_ok=True)


def delete_person_images(settings, person_id):
    shutil.rmtree(settings.faces_dir / str(person_id), ignore_errors=True)
