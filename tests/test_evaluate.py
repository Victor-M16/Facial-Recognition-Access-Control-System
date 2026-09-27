import numpy as np
import pytest

from app.cli import main
from app.config import Settings
from app.evaluate import evaluate, format_report


def at(x, y=0.0):
    """An encoding at (x, y) in the first two dimensions."""
    e = np.zeros(128)
    e[0], e[1] = x, y
    return e


# Alice's two shots are 0.3 apart; Bob's are 0.3 apart; the closest Alice/Bob pair is 0.5 apart
ENCODINGS = [at(0.0), at(0.3), at(0.8), at(1.1)]
NAMES = ["Alice", "Alice", "Bob", "Bob"]


def row(result, limit):
    return next(r for r in result.results if r.limit == limit)


def test_limit_between_same_and_different_person_distances():
    result = evaluate(ENCODINGS, NAMES, limits=[0.2, 0.4, 0.6])
    assert result.closest_pair == (pytest.approx(0.5), "Alice", "Bob")

    strict = row(result, 0.2)
    assert (strict.accepted, strict.rejected, strict.strangers_let_in) == (0, 4, 0)

    good = row(result, 0.4)
    assert (good.accepted, good.rejected, good.wrong_person, good.strangers_let_in) == (4, 0, 0, 0)

    # 0.6 is past the closest Alice/Bob pair: the facing photos let a stranger in
    loose = row(result, 0.6)
    assert loose.accepted == 4 and loose.strangers_let_in == 2


def test_burst_twins_are_ignored():
    # Each person also has a near-copy of their first photo; without ignoring it,
    # a limit of 0.05 would look like it accepts everyone
    encodings = ENCODINGS + [at(0.01), at(0.81)]
    names = NAMES + ["Alice", "Bob"]
    result = evaluate(encodings, names, limits=[0.05], twin_distance=0.2)
    assert row(result, 0.05).accepted == 0


def test_needs_two_people():
    with pytest.raises(ValueError):
        evaluate([at(0), at(0.1)], ["Alice", "Alice"])


def test_report_marks_current_limit():
    report = format_report(evaluate(ENCODINGS, NAMES, limits=[0.4, 0.6]), current_limit=0.4)
    assert "Alice and Bob, 0.500 apart" in report
    assert "<- current" in report.splitlines()[5]


def test_default_limit_is_below_bundled_lookalikes():
    # Cliff and Victor are 0.446-0.456 apart in the bundled dataset
    assert Settings().match_tolerance < 0.446


def test_cli_reads_a_legacy_pickle(tmp_path, monkeypatch, capsys):
    import pickle
    path = tmp_path / "encodings.pickle"
    path.write_bytes(pickle.dumps({"encodings": ENCODINGS, "names": NAMES}))
    monkeypatch.setenv("FRACS_DATA_DIR", str(tmp_path / "data"))
    assert main(["evaluate-threshold", "--from-pickle", str(path), "--limits", "0.4"]) == 0
    assert "Alice and Bob" in capsys.readouterr().out

    # An empty database has nothing to evaluate
    assert main(["evaluate-threshold"]) == 1
