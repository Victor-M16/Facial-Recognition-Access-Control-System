# Facial Recognition Access Control and Surveillance System (FRACS)

FRACS unlocks a door when the camera recognizes someone who has been granted access. A Raspberry Pi runs the camera, the face recognition and a web portal; an ESP32 drives the servo that moves the lock.

**Status: prototype.** It works end to end, but it can be fooled by a photo and has other limits listed under [Known limitations](#known-limitations). Don't use it as the only protection for anything that matters.

## What it does

- **Recognizes faces** from the Pi camera continuously and unlocks for people who are enrolled with access granted. An unknown face, or anyone denied access, keeps the door locked, including when they're in view alongside someone who is allowed in.
- **Web portal** (login required) to:
  - watch the live camera stream
  - enroll people: capture photos from the Pi camera or upload them, review and delete photos
  - grant or deny access per person
  - train the recognizer on new photos, with live progress; new faces work as soon as training finishes
  - lock or unlock the door remotely
- **Logs** every lock and unlock (who or what triggered it, and whether the ESP32 confirmed it), available at `/api/events`.

## How it fits together

- **Raspberry Pi** (`app/`, started by `supercam.py`): FastAPI web portal with Socket.IO for live updates, the face recognition (dlib via the `face_recognition` library, HOG detector), and a SQLite database of people, photos, face encodings, portal accounts and the access log.
- **ESP32** (`wifi_servo/`): a small web server on the local network that moves the servo. It only obeys commands signed with a secret it shares with the Pi.
- **Camera** attached to the Pi.

## When power or the network fails

The system is **fail-secure**: when something breaks, the door ends up locked. That suits a door that protects a secured area, but it means **people inside must always be able to get out mechanically** (an inside handle or thumb-turn that doesn't depend on this system). Check your local fire and building rules before fitting it to a door people could be trapped behind.

| What fails | What happens |
|---|---|
| ESP32 reboots or power returns | It drives the servo to locked before doing anything else. |
| Pi, camera, Wi-Fi or network goes down | No new unlocks. Every unlock is temporary: the ESP32 relocks by itself after 5 seconds (`UNLOCK_MS` in the firmware), so a door can't be left unlocked by a lost connection. Remote unlock is unavailable until the network is back. |
| ESP32 loses power | The servo holds its last position with little force. Because unlocks only last 5 seconds, that's almost always locked; if power is cut during an unlock, the door stays unlocked until power returns and the ESP32 relocks on boot. |
| Pi restarts | The Pi sends a lock command on startup. |
| Secrets missing or mismatched | The ESP32 refuses every command, so the door stays locked; the Pi logs an error. |

You'll need a physical way in (a key or override) for when the system is down.

Because unlocks are timed, the remote **Unlock** button also opens the door for 5 seconds. Someone who is recognized is let in once; if they stay in view, the door relocks and they need to step away for a few seconds (`FRACS_FORGET_AFTER`, default 5) and come back.

## Security

What's in place:
- **Portal login.** Every page, API route, the video stream and the live-update socket require a signed-in account. Accounts are created on the Pi from the command line (below). Passwords are stored as salted scrypt hashes. Sessions expire after 12 hours (`FRACS_SESSION_HOURS`) and are ended server-side on sign-out or password change. After 5 wrong passwords, logins from that address or for that username are refused for a minute. Requests from other websites are refused.
- **Signed lock commands.** The ESP32 only accepts commands carrying an HMAC-SHA256 signature made with a shared secret over a single-use challenge, so nobody on the network can send `unlock` themselves or replay a captured command. See `wifi_servo/fracs_auth.h` for the protocol.

What isn't:
- **Encryption is off by default.** The portal is plain HTTP unless you give it a certificate (`FRACS_SSL_CERTFILE`, `FRACS_SSL_KEYFILE`); without one, passwords cross the local network unencrypted. The link to the ESP32 is plain HTTP: commands can't be forged, but they can be seen.
- **No roles.** Every account can do everything, including managing other people's access.
- **Stored data isn't encrypted.** Photos, face encodings and the database sit in `data/` on the Pi's SD card; anyone with the card has them. Face data is sensitive personal data in many countries, so get consent from the people you enroll and delete what you no longer need.

## Known limitations

- **No liveness detection.** A photo or video of an enrolled person held up to the camera will probably unlock the door.
- **Lookalikes.** Matching takes the closest enrolled face within a distance of 0.6 (`FRACS_MATCH_TOLERANCE`). Someone who isn't enrolled but looks enough like someone who is can be let in as them. The limit hasn't been tuned on real data yet.
- **Single-frame decisions.** One frame is enough to unlock.
- **Accuracy and speed haven't been measured** on the Pi or on live camera footage. Recognition runs on the Pi's CPU and pauses while training.
- Signing out doesn't close live-update connections already open in other tabs (they stop at the next page load). Login lockouts reset when the server restarts.

## Setup

### ESP32

1. In `wifi_servo/wifi_servo.ino`, set `ssid` and `password` for your Wi-Fi, `servoPin`, and `LOCK_SECRET` to a long random value, for example from `python -c "import secrets; print(secrets.token_hex(32))"`. Until `LOCK_SECRET` is changed, the ESP32 refuses every command.
2. Flash it with the Arduino IDE (libraries: `ESPAsyncWebServer`, `ESP32Servo`). Keep `fracs_auth.h` in the same folder.

### Raspberry Pi

```bash
pip install -r requirements.txt        # dlib must be installable; on a Pi use piwheels or your distro's package
export FRACS_ESP32_URL=http://<esp32-ip>
export FRACS_ESP32_SECRET=<the same value as LOCK_SECRET>
python -m app.cli create-user <name>  # prompts for a password (8+ characters)
python supercam.py                     # serves the portal on http://<pi>:8000
```

To move the photos in `dataset/<PersonName>/` into the database and train on them in one step:

```bash
python -m app.cli import-dataset dataset --deny Pemphero --train
```

After that, people are managed from the portal: add a person, capture or upload a few photos, choose whether they're granted access, and press **Train**.

Account commands: `python -m app.cli create-user | set-password | delete-user <name>`, `python -m app.cli list-users`. Changing a password signs that account out everywhere.

Back up the `data/` folder; it holds the database and every enrolled photo.

### Settings

All settings are environment variables (see `app/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `FRACS_ESP32_URL` | unset | ESP32 address. Unset = lock commands are skipped. |
| `FRACS_ESP32_SECRET` | unset | Must match `LOCK_SECRET` in the firmware. Unset = lock commands are skipped. |
| `FRACS_DATA_DIR` | `./data` | Database and enrolled photos. |
| `FRACS_SSL_CERTFILE`, `FRACS_SSL_KEYFILE` | unset | Serve the portal over HTTPS. |
| `FRACS_SESSION_HOURS` | 12 | How long a login lasts. |
| `FRACS_MATCH_TOLERANCE` | 0.6 | Max face distance counted as a match; lower is stricter. |
| `FRACS_FORGET_AFTER` | 5 | Seconds with no face in view before the same person can trigger an unlock again. |
| `FRACS_CAMERA_INDEX`, `FRACS_CAMERA_FLIP` | 0, on | Which camera, and whether to flip the image vertically. |
| `FRACS_RECOGNITION` | on | Turn automatic recognition off (portal only). |
| `FRACS_HOST`, `FRACS_PORT` | 0.0.0.0, 8000 | Where the portal listens. |
| `FRACS_CORS_ORIGINS` | unset | Extra origins allowed to call the API. |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests don't need a camera, an ESP32 or dlib. If `g++` and the OpenSSL headers are installed, they also compile the firmware's authentication code (`wifi_servo/fracs_auth.h`) and check it against the Pi's. The rest of the firmware isn't compiled by the tests; build it with the Arduino IDE.

## Contributing
Contributions are welcome! Please fork the repository, make your changes, and submit a pull request. For major changes, please open an issue first to discuss the proposed changes.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
