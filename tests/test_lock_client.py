"""app/lock.py against a Python model of the ESP32 firmware's request checks.

tests/test_firmware_auth.py checks the real C++ (wifi_servo/fracs_auth.h) computes
the same signatures as app/lock.py.
"""
import hashlib
import hmac
import secrets

import httpx
import pytest

from app.lock import LockClient

SECRET = "0123456789abcdef0123456789abcdef"


class FakeESP32:
    def __init__(self, secret=SECRET):
        self.secret = secret
        self.nonces = set()
        self.status = 1
        self.log = []

    def handle(self, request):
        path = request.url.path
        if path == "/nonce":
            nonce = secrets.token_hex(16)
            self.nonces.add(nonce)
            return httpx.Response(200, json={"nonce": nonce})
        action = {"/lock": "lock", "/unlock": "unlock", "/lock-status": "status"}[path]
        nonce = request.headers.get("X-Fracs-Nonce")
        signature = request.headers.get("X-Fracs-Signature", "")
        if nonce not in self.nonces:
            self.log.append(("bad nonce", action))
            return httpx.Response(401)
        expected = hmac.new(self.secret.encode(), f"fracs-v1:{action}:{nonce}".encode(),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            self.log.append(("bad signature", action))
            return httpx.Response(401)
        self.nonces.discard(nonce)
        self.log.append(("ok", action))
        if action == "status":
            return httpx.Response(200, json={"status": self.status})
        self.status = 1 if action == "lock" else 0
        return httpx.Response(200)


def client_for(esp, secret=SECRET):
    return LockClient("http://esp32", secret, transport=httpx.MockTransport(esp.handle))


def test_signed_commands_are_accepted():
    esp = FakeESP32()
    lock = client_for(esp)
    assert lock.unlock() is True and esp.status == 0
    assert lock.status() == 0
    assert lock.lock() is True and esp.status == 1
    assert esp.log == [("ok", "unlock"), ("ok", "status"), ("ok", "lock")]


def test_wrong_secret_is_rejected():
    esp = FakeESP32()
    assert client_for(esp, secret="not-the-right-secret-value").unlock() is False
    assert esp.status == 1 and esp.log == [("bad signature", "unlock")]


def test_unsigned_request_is_rejected():
    # What an attacker on the network would try, and what the old firmware accepted
    esp = FakeESP32()
    transport = httpx.MockTransport(esp.handle)
    assert httpx.Client(transport=transport).post("http://esp32/unlock").status_code == 401
    assert esp.status == 1


def test_captured_request_cannot_be_replayed():
    esp = FakeESP32()
    captured = []

    def recording(request):
        captured.append(request)
        return esp.handle(request)

    lock = LockClient("http://esp32", SECRET, transport=httpx.MockTransport(recording))
    assert lock.unlock()
    lock.lock()
    replay = captured[1]  # the signed POST /unlock
    assert replay.url.path == "/unlock"
    assert esp.handle(replay).status_code == 401
    assert esp.status == 1


@pytest.mark.parametrize("url,secret", [("", SECRET), ("http://esp32", "")])
def test_missing_configuration_sends_nothing(url, secret):
    esp = FakeESP32()
    lock = LockClient(url, secret, transport=httpx.MockTransport(esp.handle))
    assert lock.unlock() is False and lock.status() is None
    assert esp.log == []


def test_unreachable_esp32_reports_failure():
    def down(request):
        raise httpx.ConnectError("no route to host")

    lock = LockClient("http://esp32", SECRET, transport=httpx.MockTransport(down))
    assert lock.unlock() is False and lock.status() is None
