# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FRACS (Facial Recognition Access Control and Surveillance System) is a Raspberry Pi Flask app. It streams a camera feed, recognizes faces, and tells an ESP32 over HTTP to drive a servo lock. The repo has no build system, no test suite and no linter config.

## Running

- **Pi server:** `python supercam.py` serves on `0.0.0.0:8000` via `socketio.run`. It uses `flask`, `flask_socketio`, `flask_sqlalchemy`, `flask_cors`, `opencv-python` (`cv2`), `face_recognition` (needs dlib), `imutils` and `requests`. There is no requirements file.
- **ESP32 firmware:** flash `wifi_servo/wifi_servo.ino` with the Arduino IDE. It needs the `ESPAsyncWebServer`, `ArduinoJson` and `ESP32Servo` libraries. Set `ssid`/`password` and `servoPin` before flashing.
- **Frontend deps:** `templates/package.json` only pulls in `flowbite` (and `templates/node_modules` is committed). The pages load most of their JS/CSS from CDNs anyway.

## Hardcoded, deployment-specific values

These are all in-source, with no config file or env vars:
- `supercam.py`: `ESP32_IP` (redacted placeholder), `UPLOAD_FOLDER = /home/mjima/flask/captured_images`, and `encodingsP = /home/mjima/flask/encodings.pickle` (absolute path; the repo root also has an `encodings.pickle`).
- The CORS origins in `supercam.py` and the AJAX URLs in `templates/index0.html` / `templates/training.html` all use `http://raspberrypi16.local:8000`.
- The authorization policy lives in `recognize_faces()`. `"Pemphero"` and `"Unknown"` trigger `lock()`, and any other known name triggers `unlock()`.

## Architecture (all in `supercam.py`)

- **Encodings model:** `encodings.pickle` is a dict `{"encodings": [...], "names": [...]}` of face_recognition 128-d embeddings. It is loaded once at import into the global `data`. `known_faces` / `known_faces_json` are derived from it.
- **Training:** `/train_model` starts `train_model()` in a thread. It sets the global `face_recognition_enabled = False` to pause recognition, re-encodes every image under `dataset/<PersonName>/` (the folder name is the label; HOG detector), writes `encodings.pickle` **relative to CWD**, and re-enables recognition. It does **not** reload the in-memory `data`, so a restart is needed before new faces are recognized. It is also a `while True` loop that keeps spinning after it finishes.
- **Camera / streaming:** `VideoCameraSingleton` shares one `cv2.VideoCapture(0)` (640x480, flipped vertically) behind a lock. `/video_feed` returns an MJPEG multipart stream from `gen()`, and each request also starts a daemon `recognize_faces` thread. Recognition is therefore only active while some client is viewing the stream, and every viewer adds another recognition thread.
- **Lock control:** `lock()`/`unlock()`/`get_lock_status()` call the ESP32 endpoints `POST /lock`, `POST /unlock` and `GET /lock-status` (returns `{"status": 0|1}`, where 1 = locked). `/api/lock` and `/api/unlock` are the browser-facing proxies. Visiting `/` also sends a lock command.
- **Socket.IO:** the default namespace broadcasts recognized names and training progress (through `handle_message`). The `/faces` namespace sends `known_faces_json` when a client connects. `index0.html` and `training.html` subscribe to both, and `index0.html` says "Do not touch this javascript especially the web sockets".
- **Other routes:** `/capture_image` (POST base64 `imageData`, saved as one overwritten `captured_image.jpg`) and `/view_captured_image`. `/record_video` renders `record_video.html`, which doesn't exist. `SQLAlchemy` is imported but not used.

## Design docs

The repo root has the use case diagram, CFG, state machine and concurrent process model (`*.drawio`, `*.png`, `*.jpg`) that describe the intended system behavior.
