from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, create_engine,
                        event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    access_granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    images: Mapped[list["FaceImage"]] = relationship(
        back_populates="person", cascade="all, delete-orphan", passive_deletes=True)


# FaceImage.status values
PENDING = "pending"      # saved, not encoded yet; the next training run picks it up
ENCODED = "encoded"      # has an encoding and is part of the recognition index
NO_FACE = "no_face"      # training found no face in it
FAILED = "failed"        # the file could not be read


class FaceImage(Base):
    __tablename__ = "face_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    # Relative to Settings.data_dir
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=PENDING, nullable=False, index=True)
    # 128 float64 values from face_recognition, stored as raw bytes
    encoding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[Person] = relationship(back_populates="images")


class AccessEvent(Base):
    __tablename__ = "access_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    # Recognized name, "Unknown", or None for remote commands
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(16))   # "lock" / "unlock"
    source: Mapped[str] = mapped_column(String(16))   # "face" / "remote" / "startup"
    success: Mapped[bool] = mapped_column(Boolean)


def make_session_factory(database_url):
    connect_args = {}
    if database_url.startswith("sqlite"):
        # Sessions are used from the camera, recognition and training threads as well as requests
        connect_args["check_same_thread"] = False
    engine = create_engine(database_url, connect_args=connect_args)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL lets the recognition thread read while training writes
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
