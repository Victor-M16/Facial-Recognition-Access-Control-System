import logging

import httpx

log = logging.getLogger(__name__)


class LockClient:
    """HTTP client for the ESP32 servo firmware in wifi_servo/wifi_servo.ino."""

    def __init__(self, base_url, timeout=3.0):
        self.base_url = base_url
        self._client = httpx.Client(timeout=timeout) if base_url else None
        if not base_url:
            log.warning("FRACS_ESP32_URL is not set; lock commands will be skipped")

    def _post(self, path):
        if self._client is None:
            return False
        try:
            return self._client.post(f"{self.base_url}{path}").status_code == 200
        except httpx.HTTPError as exc:
            log.warning("ESP32 %s failed: %s", path, exc)
            return False

    def lock(self):
        return self._post("/lock")

    def unlock(self):
        return self._post("/unlock")

    def status(self):
        """1 = locked, 0 = unlocked, None = unreachable."""
        if self._client is None:
            return None
        try:
            response = self._client.get(f"{self.base_url}/lock-status")
            if response.status_code == 200:
                return response.json()["status"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("ESP32 /lock-status failed: %s", exc)
        return None

    def close(self):
        if self._client is not None:
            self._client.close()
