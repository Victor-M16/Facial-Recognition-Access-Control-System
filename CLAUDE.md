# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FRACS (Facial Recognition Access Control and Surveillance System) is a Raspberry Pi FastAPI app. It streams a camera feed, recognizes faces, and sends signed HTTP commands to an ESP32 that drives a servo lock. People, their face photos and encodings, portal accounts and an access log are stored in SQLite. The README is kept accurate about security and limitations; update its Security, Known limitations and failure-behaviour sections when behaviour changes.

## Commands

- **Run the server:** `python supercam.py`, which is the same as `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`. `supercam.py` is now only an entry point.
- **Tests:** `pytest` (config in `pytest.ini`). Run one test with `pytest tests/test_api.py::test_people_crud`. The tests need no camera, ESP32 or dlib: `tests/conftest.py` replaces `vision.encode_faces` with a fake that turns image brightness into an identity, and passes a `FakeCamera` / `FakeLock` into `create_app(..., start_background=False)`. The `client` fixture is signed in; `anon` is not. `tests/test_firmware_auth.py` compiles `wifi_servo/fracs_auth.h` with g++ and OpenSSL (skipped if either is missing) and checks its signatures match `app/lock.py`.
- **Portal accounts:** `python -m app.cli create-user NAME` (prompts; `--password-stdin` for scripts), `set-password`, `delete-user`, `list-users`. There is no sign-up page; the login page says so when no accounts exist.
- **Import the legacy `dataset/<Name>/*.jpg` folders:** `python -m app.cli import-dataset dataset [--deny NAME] [--train]`. Train from the command line with `python -m app.cli train [--full]`.
- **ESP32 firmware:** flash `wifi_servo/wifi_servo.ino` with the Arduino IDE. It needs the `ESPAsyncWebServer` and `ESP32Servo` libraries. Set `ssid`/`password`, `servoPin` and `LOCK_SECRET` before flashing. The full sketch isn't compiled by the tests, only `fracs_auth.h`.
- There is no linter config and no frontend build step. The pages load their JS/CSS from CDNs; `templates/node_modules` is committed but mostly unused.

## Configuration

Everything is set through `FRACS_*` environment variables, read in `app/config.py` (`Settings`). `FRACS_DATA_DIR` (default `./data`, gitignored) holds `fracs.db` and `faces/<person_id>/<uuid>.jpg`. If `FRACS_ESP32_URL` or `FRACS_ESP32_SECRET` is unset, lock commands are skipped with a warning. `encodings.pickle` at the repo root belongs to the old Flask app and nothing reads it now.

## Architecture (`app/`)

- **`main.py`:** `create_app()` builds all the services, keeps them on `api.state.services`, and returns `socketio.ASGIApp(sio, other_asgi_app=api)`. Tests reach the services through `app.api.state.services`. Routes are closures inside `create_app`. On startup the lifespan starts the camera, locks the door (fail secure) and starts the recognizer.
- **Login (`auth.py` + main.py):** only `/login` and `/logout` are registered on `api`; every other route goes on the `protected` router, whose `require_user` dependency also rejects cross-origin state-changing requests. Register new routes on `protected`: `tests/test_auth.py::test_every_route_requires_login` walks all routes and fails otherwise. Unauthenticated `/api/*` and `/video_feed` get 401; pages redirect to `/login?next=`. Both Socket.IO namespaces refuse connections without a valid session cookie. Sessions live in the `login_sessions` table (the cookie holds a random token; the DB holds its SHA-256). `/docs` and `/openapi.json` are disabled.
- **ESP32 protocol (`lock.py` ↔ `wifi_servo/fracs_auth.h`):** every command is `GET /nonce`, then the request with `X-Fracs-Nonce` and `X-Fracs-Signature` = hex HMAC-SHA256(secret, `fracs-v1:<action>:<nonce>`), where the action is `lock`, `unlock` or `status`. Nonces are single use and expire after 10 s. Keep `sign()` in lock.py and `signature_hex()` in the header in step.
- **Failure behaviour is fail-secure** and is documented in the README: the ESP32 locks on power-up, every unlock relocks on the ESP32 after `UNLOCK_MS` (5 s), and the Pi locks on startup. The recognizer forgets the last person after `forget_after` seconds with no face in view, so a returning person is let in again.
- **Threads, not asyncio, do the work.** `Camera` (camera.py) has one capture thread that keeps the latest frame; the MJPEG `/video_feed` and the recognizer both read from it. `Recognizer` (recognizer.py) is one always-on thread, independent of whether anyone is watching the stream. `Trainer` (training.py) runs one background training at a time. Worker threads push Socket.IO events through `emit()` in main.py, which uses `asyncio.run_coroutine_threadsafe` on the server loop.
- **Data model (`db.py`):** `Person` (unique `name`, `access_granted`), `FaceImage` (`status`: `pending` → `encoded` / `no_face` / `failed`; `encoding` is 128 float64 values as bytes) and `AccessEvent`. Sync SQLAlchemy 2.0 on SQLite with WAL mode, and `create_all` at startup, since there are no migrations.
- **Recognition index (`face_index.py`):** an in-memory numpy copy of all `encoded` rows, rebuilt with `index.reload(session)` after training and after any change to people or images. Matching uses the nearest encoding within `match_tolerance`, not the original's vote count, which misidentified Cliff as Victor on the bundled dataset. Access comes from `Person.access_granted`; the names are no longer hardcoded.
- **Training:** a normal run encodes only `pending` images, and `full=True` re-encodes everything. It pauses the recognizer while running, commits after each image, then reloads the index and calls `recognizer.reset()`, so new faces work without a restart.
- **Access decisions (`recognizer.py`):** the recognizer only acts when the person in view changes. If anyone in the frame is unknown or denied, that face decides the frame, which keeps the door locked. Every lock/unlock goes through `AccessController` (access.py) and is logged to `access_events`.
- **Schema changes:** tables are created with `create_all` and there are no migrations. New tables are fine on an existing Pi database, but new columns on existing tables won't be added automatically.
- **`vision.py`** wraps cv2 and face_recognition with lazy imports. Call it as `vision.encode_faces(...)` through the module (not `from vision import ...`) so the test monkeypatching still works.

## Frontend / Socket.IO contract

`templates/index0.html` (dashboard) and `templates/training.html` use jQuery and Flowbite with socket.io-client 4.2:
- Default namespace: `message` is a plain string with the recognized name ("X wants access"). `training` carries the trainer status dict.
- `/faces` namespace: `message` is a **JSON string** holding a list of `{id, name, access_granted, images, encoded, pending, no_face}`. It is sent when a client connects and after every change to people, images or training.
- All AJAX calls use relative URLs to the `/api/...` routes. A global `ajaxError` handler sends the browser to `/login` on a 401. `templates/login.html` is the sign-in page; both other pages have a sign-out form posting to `/logout`. The pages carry the original author's notes asking not to touch the socket and stream JS; keep the connection and stream code as it is.

## Design docs

The repo root has the use case diagram, CFG, state machine and concurrent process model (`*.drawio`, `*.png`, `*.jpg`) that describe the intended system behavior.
