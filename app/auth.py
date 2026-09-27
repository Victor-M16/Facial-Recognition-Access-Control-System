import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from .db import LoginSession, User

COOKIE_NAME = "fracs_session"
MIN_PASSWORD_LENGTH = 8

# scrypt parameters: ~16 MB and well under a second per check on a Raspberry Pi 4
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(digest) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual.hex(), digest)


# Checked against when the username doesn't exist, so response time doesn't reveal valid usernames
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    # SQLite hands datetimes back without a timezone; they were stored as UTC
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Throttle:
    """After max_failures wrong passwords for a key, refuse that key for lockout seconds."""

    def __init__(self, max_failures=5, lockout=60.0, clock=time.monotonic):
        self.max_failures = max_failures
        self.lockout = lockout
        self.clock = clock
        self._lock = threading.Lock()
        self._state = {}  # key -> (failures, locked_until)

    def retry_after(self, key):
        with self._lock:
            _, locked_until = self._state.get(key, (0, 0.0))
            return max(0.0, locked_until - self.clock())

    def failure(self, key):
        with self._lock:
            failures, _ = self._state.get(key, (0, 0.0))
            failures += 1
            if failures >= self.max_failures:
                self._state[key] = (0, self.clock() + self.lockout)
            else:
                self._state[key] = (failures, 0.0)

    def success(self, key):
        with self._lock:
            self._state.pop(key, None)


class Auth:
    def __init__(self, session_factory, session_hours=12.0, throttle=None):
        self.session_factory = session_factory
        self.session_ttl = timedelta(hours=session_hours)
        self.throttle = throttle or Throttle()

    def has_users(self):
        with self.session_factory() as session:
            return session.scalar(select(User.id).limit(1)) is not None

    def login(self, username, password, client_ip):
        """Return (token, None) on success or (None, error message)."""
        keys = (f"ip:{client_ip}", f"user:{username.lower()}")
        wait = max(self.throttle.retry_after(k) for k in keys)
        if wait:
            return None, f"Too many failed attempts. Try again in {int(wait) + 1} seconds."

        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.username == username))
            if not verify_password(password, user.password_hash if user else _DUMMY_HASH) or user is None:
                for key in keys:
                    self.throttle.failure(key)
                return None, "Wrong username or password."
            for key in keys:
                self.throttle.success(key)
            token = secrets.token_urlsafe(32)
            now = _now()
            session.execute(delete(LoginSession).where(LoginSession.expires_at < now))
            session.add(LoginSession(token_hash=_token_hash(token), user_id=user.id,
                                     expires_at=now + self.session_ttl))
            session.commit()
            return token, None

    def user_for_token(self, token):
        """The signed-in User for a session cookie value, or None."""
        if not token:
            return None
        with self.session_factory() as session:
            login = session.scalar(select(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
            if login is None or _aware(login.expires_at) <= _now():
                return None
            user = login.user
            session.expunge(user)
            return user

    def logout(self, token):
        if not token:
            return
        with self.session_factory() as session:
            session.execute(delete(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
            session.commit()

    # ---- account management (used by the CLI) ----

    def create_user(self, username, password):
        check_password(password)
        with self.session_factory() as session:
            session.add(User(username=username, password_hash=hash_password(password)))
            session.commit()

    def set_password(self, username, password):
        """Change a password and sign that user out everywhere. Returns False if no such user."""
        check_password(password)
        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.username == username))
            if user is None:
                return False
            user.password_hash = hash_password(password)
            session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            session.commit()
            return True

    def delete_user(self, username):
        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.username == username))
            if user is None:
                return False
            session.delete(user)
            session.commit()
            return True

    def list_users(self):
        with self.session_factory() as session:
            return list(session.scalars(select(User.username).order_by(User.username)))


def check_password(password):
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
