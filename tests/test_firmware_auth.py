"""Compile and run the firmware's auth logic (wifi_servo/fracs_auth.h) on this machine.

OpenSSL stands in for the ESP32's mbedtls. Skipped when g++ or the OpenSSL
headers aren't installed.
"""
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest

from app.lock import sign

HERE = Path(__file__).parent
SOURCE = HERE / "firmware" / "test_fracs_auth.cpp"


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    if shutil.which("g++") is None or not Path("/usr/include/openssl/hmac.h").exists():
        pytest.skip("needs g++ and OpenSSL headers")
    out = tmp_path_factory.mktemp("firmware") / "test_fracs_auth"
    subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(SOURCE), "-lcrypto", "-o", str(out)],
                   check=True)
    return out


def test_firmware_auth_checks(binary):
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("action", ["lock", "unlock", "status"])
def test_pi_and_firmware_compute_the_same_signature(binary, action):
    secret, nonce = secrets.token_hex(32), secrets.token_hex(16)
    result = subprocess.run([str(binary), "sign", secret, action, nonce], capture_output=True, text=True,
                            check=True)
    assert result.stdout.strip() == sign(secret, action, nonce)
