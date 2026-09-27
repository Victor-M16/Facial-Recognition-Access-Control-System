import hashlib
import hmac
import logging

import httpx

log = logging.getLogger(__name__)


def sign(secret, action, nonce):
    """HMAC the ESP32 checks; must match fracs::signature_hex in wifi_servo/fracs_auth.h."""
    return hmac.new(secret.encode(), f"fracs-v1:{action}:{nonce}".encode(), hashlib.sha256).hexdigest()


class LockClient:
    """HTTP client for the ESP32 servo firmware in wifi_servo/wifi_servo.ino.

    Every command fetches a single-use nonce from the ESP32 and signs it with
    the shared secret (see wifi_servo/fracs_auth.h for the protocol).
    """

    def __init__(self, base_url, secret, timeout=3.0, transport=None):
        self.base_url = base_url
        self.secret = secret
        self._client = None
        if not base_url:
            log.warning("FRACS_ESP32_URL is not set; lock commands will be skipped")
        elif not secret:
            # Without a secret the ESP32 would refuse the commands anyway
            log.error("FRACS_ESP32_SECRET is not set; lock commands will be skipped")
        else:
            self._client = httpx.Client(timeout=timeout, transport=transport)

    def _signed(self, method, path, action):
        nonce = self._client.get(f"{self.base_url}/nonce").json()["nonce"]
        headers = {"X-Fracs-Nonce": nonce, "X-Fracs-Signature": sign(self.secret, action, nonce)}
        response = self._client.request(method, f"{self.base_url}{path}", headers=headers)
        if response.status_code == 401:
            log.error("ESP32 rejected the %s signature; check FRACS_ESP32_SECRET matches LOCK_SECRET", action)
        elif response.status_code == 503:
            log.error("ESP32 has no LOCK_SECRET configured; set it in wifi_servo.ino and reflash")
        return response

    def _command(self, path, action):
        if self._client is None:
            return False
        try:
            return self._signed("POST", path, action).status_code == 200
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("ESP32 %s failed: %s", path, exc)
            return False

    def lock(self):
        return self._command("/lock", "lock")

    def unlock(self):
        """Unlocks for the ESP32's UNLOCK_MS; it relocks on its own."""
        return self._command("/unlock", "unlock")

    def status(self):
        """1 = locked, 0 = unlocked, None = unreachable or not configured."""
        if self._client is None:
            return None
        try:
            response = self._signed("GET", "/lock-status", "status")
            if response.status_code == 200:
                return response.json()["status"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("ESP32 /lock-status failed: %s", exc)
        return None

    def close(self):
        if self._client is not None:
            self._client.close()
