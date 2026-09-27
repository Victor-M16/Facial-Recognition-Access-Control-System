import threading

import numpy as np
from sqlalchemy import select

from app import vision
from app.db import AccessEvent
from conftest import fake_encode_faces, jpeg


def enroll(client, name, *levels, access=True):
    person = client.post("/api/people", json={"name": name, "access_granted": access}).json()
    if levels:
        files = [("files", (f"{i}.jpg", jpeg(level), "image/jpeg")) for i, level in enumerate(levels)]
        assert client.post(f"/api/people/{person['id']}/images", files=files).status_code == 201
    return person


def train(client, services, full=False):
    assert client.post("/api/training", json={"full": full}).status_code == 202
    services.trainer.wait(10)
    return client.get("/api/training").json()


def test_pages_render(client):
    assert "Face Recognition Access Control System" in client.get("/").text
    assert client.get("/training").status_code == 200


def test_people_crud(client):
    alice = enroll(client, " Alice ")
    assert alice["name"] == "Alice"

    assert client.post("/api/people", json={"name": "Alice"}).status_code == 409
    assert client.post("/api/people", json={"name": ""}).status_code == 422

    r = client.patch(f"/api/people/{alice['id']}", json={"access_granted": False})
    assert r.json()["access_granted"] is False

    [row] = client.get("/api/people").json()
    assert row == {"id": alice["id"], "name": "Alice", "access_granted": False,
                   "images": 0, "encoded": 0, "pending": 0, "no_face": 0}

    assert client.delete(f"/api/people/{alice['id']}").status_code == 204
    assert client.get("/api/people").json() == []
    assert client.delete(f"/api/people/{alice['id']}").status_code == 404


def test_upload_rejects_non_images(client):
    alice = enroll(client, "Alice")
    files = [("files", ("notes.txt", b"not an image", "text/plain"))]
    assert client.post(f"/api/people/{alice['id']}/images", files=files).status_code == 400

    files.append(("files", ("face.jpg", jpeg(100), "image/jpeg")))
    body = client.post(f"/api/people/{alice['id']}/images", files=files).json()
    assert len(body["added"]) == 1 and body["rejected"] == ["notes.txt"]


def test_training_is_incremental_and_reloads_index(client, services):
    enroll(client, "Alice", 100, 100)
    status = train(client, services)
    assert status["state"] == "done" and status["total"] == 2 and status["encoded"] == 2
    assert services.index.size == 2
    assert services.index.match(fake_encode_faces(np.full((1, 1, 3), 100))[0]).name == "Alice"

    # A new person only encodes their own images, and is recognized without a restart
    enroll(client, "Bob", 150)
    status = train(client, services)
    assert status["total"] == 1
    assert services.index.size == 3
    assert services.index.match(fake_encode_faces(np.full((1, 1, 3), 150))[0]).name == "Bob"

    status = train(client, services, full=True)
    assert status["total"] == 3 and services.index.size == 3


def test_images_without_faces_are_reported(client, services):
    alice = enroll(client, "Alice", 100, 0)
    status = train(client, services)
    assert status["encoded"] == 1 and status["no_face"] == 1
    [row] = client.get("/api/people").json()
    assert (row["encoded"], row["no_face"], row["pending"]) == (1, 1, 0)

    images = client.get(f"/api/people/{alice['id']}/images").json()
    assert {i["status"] for i in images} == {"encoded", "no_face"}
    assert client.get(images[0]["url"]).headers["content-type"] == "image/jpeg"


def test_capture_from_camera(client, services, camera):
    alice = enroll(client, "Alice")
    image = client.post(f"/api/people/{alice['id']}/capture").json()
    assert image["status"] == "pending"
    assert train(client, services)["encoded"] == 1

    camera.frame = None
    assert client.post(f"/api/people/{alice['id']}/capture").status_code == 503


def test_deleting_removes_from_index_and_disk(client, services, settings):
    alice = enroll(client, "Alice", 100, 100)
    train(client, services)
    images = client.get(f"/api/people/{alice['id']}/images").json()

    assert client.delete(f"/api/images/{images[0]['id']}").status_code == 204
    assert services.index.size == 1

    client.delete(f"/api/people/{alice['id']}")
    assert services.index.size == 0
    assert not (settings.faces_dir / str(alice["id"])).exists()


def test_access_change_applies_without_retraining(client, services):
    alice = enroll(client, "Alice", 100)
    train(client, services)
    encoding = fake_encode_faces(np.full((1, 1, 3), 100))[0]
    assert services.index.match(encoding).access_granted is True
    client.patch(f"/api/people/{alice['id']}", json={"access_granted": False})
    assert services.index.match(encoding).access_granted is False


def test_training_rejects_concurrent_runs(client, services, monkeypatch):
    release = threading.Event()

    def slow_encode(rgb, model="hog"):
        release.wait(5)
        return fake_encode_faces(rgb)

    monkeypatch.setattr(vision, "encode_faces", slow_encode)
    enroll(client, "Alice", 100)
    assert client.post("/api/training").status_code == 202
    assert services.recognizer.paused
    assert client.post("/api/training").status_code == 409
    release.set()
    services.trainer.wait(10)
    assert client.get("/api/training").json()["state"] == "done"
    assert not services.recognizer.paused


def test_remote_lock_routes_log_events(client, services, lock):
    assert client.post("/api/unlock").status_code == 200
    lock.ok = False
    assert client.post("/api/lock").status_code == 502
    assert lock.calls == ["unlock", "lock"]
    assert client.get("/api/lock/status").json() == {"status": 1}

    events = client.get("/api/events").json()
    assert [(e["action"], e["source"], e["success"], e["name"]) for e in events] == [
        ("lock", "remote", False, "admin"), ("unlock", "remote", True, "admin")]


def test_startup_locks_the_door(settings, camera, lock):
    from fastapi.testclient import TestClient
    from app.main import create_app

    settings.recognition_enabled = False
    app = create_app(settings, camera=camera, lock_client=lock)
    with TestClient(app):
        pass
    assert lock.calls == ["lock"]
    with app.api.state.services.session_factory() as session:
        [event] = session.scalars(select(AccessEvent)).all()
        assert event.source == "startup"


def test_training_with_nothing_new(client, services):
    status = train(client, services)
    assert status["state"] == "done" and status["total"] == 0
    assert status["message"].startswith("Nothing new to train on")
