import asyncio
import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import socketio
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from . import storage, vision
from .access import AccessController
from .camera import Camera
from .config import REPO_ROOT, Settings
from .db import ENCODED, NO_FACE, PENDING, AccessEvent, FaceImage, Person, make_session_factory
from .face_index import FaceIndex
from .lock import LockClient
from .recognizer import Recognizer
from .training import Trainer

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    access_granted: bool = True


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    access_granted: bool | None = None


class TrainRequest(BaseModel):
    full: bool = False


def people_payload(session):
    count = lambda status: func.coalesce(func.sum(case((FaceImage.status == status, 1), else_=0)), 0)
    rows = session.execute(
        select(Person, func.count(FaceImage.id), count(ENCODED), count(PENDING), count(NO_FACE))
        .outerjoin(FaceImage)
        .group_by(Person.id)
        .order_by(Person.name)
    ).all()
    return [
        {"id": p.id, "name": p.name, "access_granted": p.access_granted,
         "images": total, "encoded": encoded, "pending": pending, "no_face": no_face}
        for p, total, encoded, pending, no_face in rows
    ]


def image_payload(image):
    return {"id": image.id, "person_id": image.person_id, "status": image.status,
            "url": f"/api/images/{image.id}", "created_at": image.created_at.isoformat()}


def create_app(settings=None, *, camera=None, lock_client=None, start_background=True):
    """Build the ASGI app. Run with: uvicorn app.main:create_app --factory"""
    settings = settings or Settings()
    settings.ensure_dirs()
    session_factory = make_session_factory(settings.database_url)
    templates = Jinja2Templates(directory=str(REPO_ROOT / "templates"))

    # Default cors_allowed_origins (None) = same origin only, which covers the pages we serve
    sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.cors_origins or None)
    loop_ref = SimpleNamespace(loop=None)

    def emit(event, data, namespace="/"):
        # Called from worker threads; hand the coroutine to the server's event loop
        loop = loop_ref.loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(sio.emit(event, data, namespace=namespace), loop)

    def people_json():
        with session_factory() as session:
            return json.dumps(people_payload(session))

    def broadcast_people():
        emit("message", people_json(), namespace="/faces")

    index = FaceIndex(settings.match_tolerance)
    with session_factory() as session:
        index.reload(session)

    lock_client = lock_client or LockClient(settings.esp32_url, settings.esp32_timeout)
    access = AccessController(lock_client, session_factory)
    camera = camera or Camera(settings.camera_index, settings.camera_flip)
    # Recognized names go to the default namespace as plain 'message' strings, as before
    recognizer = Recognizer(camera, index, access, notify=lambda name: emit("message", name),
                            detection_model=settings.detection_model)

    def training_finished():
        recognizer.reset()
        recognizer.resume()
        broadcast_people()

    trainer = Trainer(session_factory, settings, index,
                      on_progress=lambda status: emit("training", status),
                      on_start=recognizer.pause, on_finish=training_finished)

    def people_changed(session):
        index.reload(session)
        recognizer.reset()
        broadcast_people()

    @asynccontextmanager
    async def lifespan(_):
        loop_ref.loop = asyncio.get_running_loop()
        if start_background:
            camera.start()
            # Fail secure: the door starts locked whenever the server starts
            await run_in_threadpool(access.lock, None, "startup")
            if settings.recognition_enabled:
                recognizer.start()
        yield
        recognizer.stop()
        camera.stop()
        lock_client.close()
        loop_ref.loop = None

    api = FastAPI(title="FRACS", lifespan=lifespan)
    if settings.cors_origins:
        api.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_methods=["*"], allow_headers=["*"])

    api.state.services = SimpleNamespace(
        settings=settings, session_factory=session_factory, index=index, access=access,
        camera=camera, recognizer=recognizer, trainer=trainer, sio=sio)

    # ---- pages ----

    @api.get("/", include_in_schema=False)
    def index_page(request: Request):
        return templates.TemplateResponse(request, "index0.html")

    @api.get("/training", include_in_schema=False)
    def training_page(request: Request):
        return templates.TemplateResponse(request, "training.html")

    @api.get("/video_feed", include_in_schema=False)
    async def video_feed():
        if not camera.available:
            raise HTTPException(503, "Camera not available")

        async def frames():
            last = 0
            while not camera.stopped:
                frame_id, frame = await run_in_threadpool(camera.wait_for_frame, last, 1.0)
                if frame is None:
                    break
                if frame_id == last:
                    continue
                last = frame_id
                jpeg = vision.encode_jpeg(frame, quality=80)
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    # ---- lock ----

    @api.post("/api/lock")
    def lock_route():
        if not access.lock(source="remote"):
            raise HTTPException(502, "Failed to send lock command")
        return {"message": "Lock command sent successfully"}

    @api.post("/api/unlock")
    def unlock_route():
        if not access.unlock(source="remote"):
            raise HTTPException(502, "Failed to send unlock command")
        return {"message": "Unlock command sent successfully"}

    @api.get("/api/lock/status")
    def lock_status():
        return {"status": access.status()}

    @api.get("/api/events")
    def list_events(limit: int = 50):
        with session_factory() as session:
            events = session.scalars(
                select(AccessEvent).order_by(AccessEvent.id.desc()).limit(min(max(limit, 1), 500)))
            return [{"id": e.id, "timestamp": e.timestamp.isoformat(), "name": e.name,
                     "action": e.action, "source": e.source, "success": e.success} for e in events]

    # ---- people ----

    def get_person(session, person_id):
        person = session.get(Person, person_id)
        if person is None:
            raise HTTPException(404, "Person not found")
        return person

    @api.get("/api/people")
    def list_people():
        with session_factory() as session:
            return people_payload(session)

    @api.post("/api/people", status_code=201)
    def create_person(body: PersonCreate):
        name = body.name.strip()
        if not name:
            raise HTTPException(422, "Name is required")
        with session_factory() as session:
            person = Person(name=name, access_granted=body.access_granted)
            session.add(person)
            try:
                session.commit()
            except IntegrityError:
                raise HTTPException(409, f"{name} is already enrolled")
            people_changed(session)
            return {"id": person.id, "name": person.name, "access_granted": person.access_granted}

    @api.patch("/api/people/{person_id}")
    def update_person(person_id: int, body: PersonUpdate):
        with session_factory() as session:
            person = get_person(session, person_id)
            if body.name is not None and body.name.strip():
                person.name = body.name.strip()
            if body.access_granted is not None:
                person.access_granted = body.access_granted
            try:
                session.commit()
            except IntegrityError:
                raise HTTPException(409, f"{body.name} is already enrolled")
            people_changed(session)
            return {"id": person.id, "name": person.name, "access_granted": person.access_granted}

    @api.delete("/api/people/{person_id}", status_code=204)
    def delete_person(person_id: int):
        with session_factory() as session:
            session.delete(get_person(session, person_id))
            session.commit()
            storage.delete_person_images(settings, person_id)
            people_changed(session)
        return Response(status_code=204)

    # ---- images ----

    @api.get("/api/people/{person_id}/images")
    def list_images(person_id: int):
        with session_factory() as session:
            person = get_person(session, person_id)
            return [image_payload(i) for i in sorted(person.images, key=lambda i: i.id)]

    def add_image(session, person_id, frame):
        image = FaceImage(person_id=person_id, path=storage.save_face_image(settings, person_id, frame))
        session.add(image)
        return image

    @api.post("/api/people/{person_id}/images", status_code=201)
    def upload_images(person_id: int, files: list[UploadFile] = File(...)):
        with session_factory() as session:
            get_person(session, person_id)
            added, rejected = [], []
            for upload in files:
                data = upload.file.read(MAX_UPLOAD_BYTES + 1)
                frame = vision.decode_image(data) if len(data) <= MAX_UPLOAD_BYTES else None
                if frame is None:
                    rejected.append(upload.filename)
                    continue
                added.append(add_image(session, person_id, frame))
            if not added:
                raise HTTPException(400, "No valid images uploaded (JPEG/PNG up to 10 MB)")
            session.commit()
            broadcast_people()
            return {"added": [image_payload(i) for i in added], "rejected": rejected}

    @api.post("/api/people/{person_id}/capture", status_code=201)
    def capture_image(person_id: int):
        _, frame = camera.latest_frame()
        if frame is None:
            raise HTTPException(503, "Camera not available")
        with session_factory() as session:
            get_person(session, person_id)
            image = add_image(session, person_id, frame)
            session.commit()
            broadcast_people()
            return image_payload(image)

    @api.get("/api/images/{image_id}")
    def get_image(image_id: int):
        with session_factory() as session:
            image = session.get(FaceImage, image_id)
            if image is None or not (settings.data_dir / image.path).exists():
                raise HTTPException(404, "Image not found")
            return FileResponse(settings.data_dir / image.path, media_type="image/jpeg")

    @api.delete("/api/images/{image_id}", status_code=204)
    def delete_image(image_id: int):
        with session_factory() as session:
            image = session.get(FaceImage, image_id)
            if image is None:
                raise HTTPException(404, "Image not found")
            session.delete(image)
            session.commit()
            storage.delete_face_image(settings, image.path)
            people_changed(session)
        return Response(status_code=204)

    # ---- training ----

    @api.post("/api/training", status_code=202)
    def start_training(body: TrainRequest | None = None):
        if not trainer.start(full=bool(body and body.full)):
            raise HTTPException(409, "Training is already running")
        return trainer.status()

    @api.get("/api/training")
    def training_status():
        return trainer.status()

    # ---- Socket.IO ----

    @sio.on("connect")
    async def connect(sid, environ):
        pass

    @sio.on("connect", namespace="/faces")
    async def connect_faces(sid, environ):
        await sio.emit("message", await run_in_threadpool(people_json), to=sid, namespace="/faces")

    asgi = socketio.ASGIApp(sio, other_asgi_app=api)
    asgi.api = api
    return asgi
