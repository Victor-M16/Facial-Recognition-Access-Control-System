"""Command-line helpers.

    python -m app.cli import-dataset dataset [--deny NAME ...] [--train]
    python -m app.cli train [--full]
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from . import storage, vision
from .config import Settings
from .db import FaceImage, Person, make_session_factory
from .face_index import FaceIndex
from .training import Trainer

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def import_dataset(settings, session_factory, root, deny=()):
    """Enroll every <root>/<PersonName>/<image> as a pending image of that person."""
    root = Path(root)
    added = 0
    with session_factory() as session:
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            person = session.scalar(select(Person).where(Person.name == folder.name))
            if person is None:
                person = Person(name=folder.name, access_granted=folder.name not in deny)
                session.add(person)
                session.flush()
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                frame = vision.decode_image(path.read_bytes())
                if frame is None:
                    print(f"skipping unreadable {path}", file=sys.stderr)
                    continue
                session.add(FaceImage(person_id=person.id,
                                      path=storage.save_face_image(settings, person.id, frame)))
                added += 1
            print(f"{folder.name}: enrolled")
        session.commit()
    return added


def run_training(settings, session_factory, full=False):
    trainer = Trainer(session_factory, settings, FaceIndex(settings.match_tolerance),
                      on_progress=lambda s: print(s["message"]))
    trainer.start(full=full)
    trainer.wait()
    return trainer.status()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-dataset", help="enroll images from <dir>/<PersonName>/*.jpg")
    imp.add_argument("directory")
    imp.add_argument("--deny", action="append", default=[], metavar="NAME",
                     help="enroll this person with access denied (repeatable)")
    imp.add_argument("--train", action="store_true", help="train right after importing")
    train = sub.add_parser("train", help="encode pending images")
    train.add_argument("--full", action="store_true", help="re-encode every image")
    args = parser.parse_args(argv)

    settings = Settings()
    settings.ensure_dirs()
    session_factory = make_session_factory(settings.database_url)
    if args.command == "import-dataset":
        print(f"added {import_dataset(settings, session_factory, args.directory, args.deny)} image(s)")
        if args.train:
            run_training(settings, session_factory)
    elif args.command == "train":
        status = run_training(settings, session_factory, full=args.full)
        return 0 if status["state"] == "done" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
