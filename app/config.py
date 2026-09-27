import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name):
    value = os.environ.get(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    # Everything the app writes (SQLite database, enrolled face images) lives here
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("FRACS_DATA_DIR", REPO_ROOT / "data")))
    database_url: str = field(default_factory=lambda: os.environ.get("FRACS_DATABASE_URL", ""))
    # Base URL of the ESP32 lock controller, e.g. http://192.168.1.50. Unset = lock calls are skipped
    esp32_url: str = field(default_factory=lambda: os.environ.get("FRACS_ESP32_URL", "").rstrip("/"))
    # Shared with LOCK_SECRET in wifi_servo.ino; every command is signed with it
    esp32_secret: str = field(default_factory=lambda: os.environ.get("FRACS_ESP32_SECRET", ""))
    esp32_timeout: float = field(default_factory=lambda: float(os.environ.get("FRACS_ESP32_TIMEOUT", "3")))
    camera_index: int = field(default_factory=lambda: int(os.environ.get("FRACS_CAMERA_INDEX", "0")))
    # The original Pi camera mount was upside down, so frames were flipped vertically
    camera_flip: bool = field(default_factory=lambda: _env_bool("FRACS_CAMERA_FLIP", True))
    recognition_enabled: bool = field(default_factory=lambda: _env_bool("FRACS_RECOGNITION", True))
    # Max face distance that counts as a match; lower is stricter. face_recognition's own
    # default of 0.6 let 82 of 94 bundled photos in as someone else when their owner wasn't
    # enrolled; no two different people in the dataset are closer than 0.456. 0.4 keeps a
    # margin below that. Re-measure on your own faces: python -m app.cli evaluate-threshold
    match_tolerance: float = field(default_factory=lambda: float(os.environ.get("FRACS_MATCH_TOLERANCE", "0.4")))
    # "hog" is the only practical detector on a Raspberry Pi; "cnn" needs a GPU
    detection_model: str = field(default_factory=lambda: os.environ.get("FRACS_DETECTION_MODEL", "hog"))
    # After this many seconds with no face in view, the recognizer forgets who it last saw,
    # so the same person coming back is recognized (and let in) again
    forget_after: float = field(default_factory=lambda: float(os.environ.get("FRACS_FORGET_AFTER", "5")))
    # How long a portal login lasts
    session_hours: float = field(default_factory=lambda: float(os.environ.get("FRACS_SESSION_HOURS", "12")))
    cors_origins: list = field(default_factory=lambda: _env_list("FRACS_CORS_ORIGINS"))

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'fracs.db'}"

    @property
    def faces_dir(self):
        return self.data_dir / "faces"

    def ensure_dirs(self):
        self.faces_dir.mkdir(parents=True, exist_ok=True)
