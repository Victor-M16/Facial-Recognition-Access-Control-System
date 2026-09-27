import re
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import update

from app.auth import COOKIE_NAME, Throttle, hash_password, verify_password
from app.db import LoginSession
from conftest import PASSWORD, USERNAME

PUBLIC = {"/login", "/logout"}


def all_routes(routes):
    # Newer FastAPI keeps included routers as a wrapper rather than copying their routes in
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from all_routes(route.original_router.routes)


def test_every_route_requires_login(app, anon):
    routes = [r for r in all_routes(app.api.routes) if r.path not in PUBLIC]
    assert len(routes) > 15
    for route in routes:
        path = re.sub(r"\{[^}]+\}", "1", route.path)
        for method in route.methods:
            r = anon.request(method, path, follow_redirects=False)
            if path.startswith("/api/") or path == "/video_feed":
                assert r.status_code == 401, (method, path)
            else:
                assert r.status_code == 303, (method, path)
                assert r.headers["location"] == f"/login?next={path}"


def test_api_docs_are_not_public(anon):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert anon.get(path).status_code == 404


def test_login_page_says_when_no_accounts_exist(anon, services):
    assert "No accounts exist yet" in anon.get("/login").text
    services.auth.create_user("someone", "long enough password")
    assert "No accounts exist yet" not in anon.get("/login").text


def test_login_logout_flow(anon, services):
    services.auth.create_user(USERNAME, PASSWORD)

    r = anon.post("/login", data={"username": USERNAME, "password": "wrong password"})
    assert r.status_code == 401 and "Wrong username or password" in r.text
    r = anon.post("/login", data={"username": "nobody", "password": PASSWORD})
    assert r.status_code == 401 and "Wrong username or password" in r.text

    r = anon.post("/login", data={"username": USERNAME, "password": PASSWORD, "next": "/training"},
                  follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/training"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert anon.get("/api/people").status_code == 200
    token = anon.cookies[COOKIE_NAME]

    anon.post("/logout", follow_redirects=False)
    assert anon.get("/api/people").status_code == 401
    # The old token is dead on the server, not just deleted from the browser
    anon.cookies.set(COOKIE_NAME, token)
    assert anon.get("/api/people").status_code == 401


@pytest.mark.parametrize("next_path", ["//evil.example", "https://evil.example", "/\\evil.example", ""])
def test_login_never_redirects_off_site(anon, services, next_path):
    services.auth.create_user(USERNAME, PASSWORD)
    r = anon.post("/login", data={"username": USERNAME, "password": PASSWORD, "next": next_path},
                  follow_redirects=False)
    assert r.headers["location"] == "/"


def test_expired_session_is_rejected(client, services):
    assert client.get("/api/people").status_code == 200
    with services.session_factory() as session:
        session.execute(update(LoginSession).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        session.commit()
    assert client.get("/api/people").status_code == 401


def test_changing_password_signs_user_out(client, services):
    services.auth.set_password(USERNAME, "a brand new password")
    assert client.get("/api/people").status_code == 401


def test_cross_site_requests_are_refused(client):
    assert client.post("/api/unlock", headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/unlock", headers={"Origin": "http://testserver"}).status_code == 200


def test_repeated_failures_lock_out_login(anon, services):
    services.auth.create_user(USERNAME, PASSWORD)
    for _ in range(5):
        anon.post("/login", data={"username": USERNAME, "password": "wrong password"})
    r = anon.post("/login", data={"username": USERNAME, "password": PASSWORD})
    assert r.status_code == 401 and "Too many failed attempts" in r.text


def test_throttle_expires():
    now = [0.0]
    throttle = Throttle(max_failures=2, lockout=60, clock=lambda: now[0])
    throttle.failure("k")
    assert throttle.retry_after("k") == 0
    throttle.failure("k")
    assert throttle.retry_after("k") == 60
    now[0] = 61
    assert throttle.retry_after("k") == 0


def test_password_hashing():
    stored = hash_password("s3cret password")
    assert stored.startswith("scrypt$") and "s3cret" not in stored
    assert verify_password("s3cret password", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("anything", "garbage")
    assert hash_password("same") != hash_password("same")  # salted


def test_short_passwords_are_refused(services):
    with pytest.raises(ValueError):
        services.auth.create_user("someone", "short")


def test_remote_commands_record_who_sent_them(client):
    client.post("/api/unlock")
    [event] = client.get("/api/events").json()
    assert (event["name"], event["source"]) == (USERNAME, "remote")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_socketio_requires_login(app, services):
    socketio = pytest.importorskip("socketio")
    pytest.importorskip("websocket")
    import httpx
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        url = f"http://127.0.0.1:{port}"

        anonymous = socketio.Client()
        with pytest.raises(socketio.exceptions.ConnectionError):
            anonymous.connect(url, namespaces=["/faces"], wait_timeout=5)

        services.auth.create_user(USERNAME, PASSWORD)
        r = httpx.post(f"{url}/login", data={"username": USERNAME, "password": PASSWORD})
        token = r.cookies[COOKIE_NAME] if COOKIE_NAME in r.cookies else r.history[0].cookies[COOKIE_NAME]
        received = []
        signed_in = socketio.Client()
        signed_in.on("message", received.append, namespace="/faces")
        signed_in.connect(url, namespaces=["/", "/faces"], headers={"Cookie": f"{COOKIE_NAME}={token}"},
                          wait_timeout=5)
        for _ in range(50):
            if received:
                break
            time.sleep(0.05)
        signed_in.disconnect()
        assert received == ["[]"]
    finally:
        server.should_exit = True
        thread.join(5)
