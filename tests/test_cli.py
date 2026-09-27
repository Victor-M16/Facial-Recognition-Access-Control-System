from app.cli import import_dataset, run_training
from app.db import make_session_factory
from app.face_index import FaceIndex
from conftest import jpeg


def test_import_dataset_then_train(tmp_path, settings):
    for name, level in [("Victor", 100), ("Pemphero", 150)]:
        (tmp_path / "dataset" / name).mkdir(parents=True)
        (tmp_path / "dataset" / name / "image_0.jpg").write_bytes(jpeg(level))
    (tmp_path / "dataset" / "Victor" / "notes.txt").write_text("ignored")

    settings.ensure_dirs()
    session_factory = make_session_factory(settings.database_url)
    assert import_dataset(settings, session_factory, tmp_path / "dataset", deny=["Pemphero"]) == 2

    assert run_training(settings, session_factory)["encoded"] == 2
    index = FaceIndex()
    with session_factory() as session:
        index.reload(session)
    assert index.size == 2
    assert {name: access for name, access in index._snapshot.people.values()} == {
        "Victor": True, "Pemphero": False}
