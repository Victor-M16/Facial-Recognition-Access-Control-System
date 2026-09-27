"""Measure how a match limit (FRACS_MATCH_TOLERANCE) performs on the enrolled faces.

Two questions for each candidate limit:

- Enrolled people: hold out each photo and match it against all the others.
  Is it accepted as the right person, rejected, or taken for someone else?
  Photos taken in a burst are near-copies of each other, which would make this
  look better than a live camera frame will be, so same-person photos closer
  than `twin_distance` to the probe are ignored.
- Strangers: take each person out of the index and use their photos as a
  stranger at the door. How many would be let in as someone else?

A good limit lets no strangers in while still accepting enrolled people.
Because the recognizer checks several frames a second, an occasional rejected
frame costs little; a stranger let in once opens the door.
"""
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select

from .db import ENCODED, FaceImage, Person

DEFAULT_LIMITS = (0.35, 0.4, 0.45, 0.5, 0.55, 0.6)


@dataclass(frozen=True)
class LimitResult:
    limit: float
    probes: int           # enrolled photos that had another (non-twin) photo of the same person
    accepted: int
    rejected: int
    wrong_person: int
    strangers: int        # photos tried as a stranger
    strangers_let_in: int


@dataclass(frozen=True)
class Evaluation:
    people: int
    photos: int
    closest_pair: tuple   # (distance, name_a, name_b): the two most alike different people
    results: list


def load_encodings(session):
    rows = session.execute(
        select(Person.name, FaceImage.encoding)
        .join(FaceImage, FaceImage.person_id == Person.id)
        .where(FaceImage.status == ENCODED)
    ).all()
    names = [name for name, _ in rows]
    encodings = [np.frombuffer(enc, dtype=np.float64) for _, enc in rows]
    return encodings, names


def evaluate(encodings, names, limits=DEFAULT_LIMITS, twin_distance=0.2):
    E = np.asarray(encodings, dtype=np.float64)
    N = np.asarray(names)
    people = sorted(set(names))
    if len(people) < 2:
        raise ValueError("Need encoded photos of at least two people to evaluate a limit")

    D = np.linalg.norm(E[:, None, :] - E[None, :, :], axis=2)
    same = N[:, None] == N[None, :]
    # For the enrolled test, a probe can't match itself or its own burst twins
    candidates = ~(same & (D < twin_distance))

    different = np.where(same, np.inf, D)
    i, j = np.unravel_index(np.argmin(different), D.shape)
    closest_pair = (float(D[i, j]), str(N[i]), str(N[j]))

    # Nearest photo of anyone else, for each photo: what a stranger at the door would match
    stranger_nearest = different.min(axis=1)

    results = []
    for limit in limits:
        accepted = rejected = wrong = probes = 0
        for p in range(len(E)):
            if not (candidates[p] & same[p]).any():
                continue  # no other shot of this person to match against
            probes += 1
            best = int(np.argmin(np.where(candidates[p], D[p], np.inf)))
            if D[p, best] > limit:
                rejected += 1
            elif same[p, best]:
                accepted += 1
            else:
                wrong += 1
        results.append(LimitResult(limit, probes, accepted, rejected, wrong,
                                   len(E), int((stranger_nearest <= limit).sum())))
    return Evaluation(len(people), len(E), closest_pair, results)


def format_report(evaluation, current_limit=None):
    distance, a, b = evaluation.closest_pair
    lines = [
        f"{evaluation.photos} encoded photos of {evaluation.people} people.",
        f"The two most alike different people are {a} and {b}, {distance:.3f} apart:",
        "a limit at or above that lets one in as the other.",
        "",
        f"{'limit':>6}  {'enrolled accepted':>17}  {'rejected':>8}  {'wrong person':>12}  {'strangers let in':>16}",
    ]
    for r in evaluation.results:
        marker = "  <- current" if current_limit is not None and abs(r.limit - current_limit) < 1e-9 else ""
        lines.append(f"{r.limit:>6.2f}  {r.accepted:>8}/{r.probes:<8}  {r.rejected:>8}  {r.wrong_person:>12}  "
                     f"{r.strangers_let_in:>7}/{r.strangers:<8}{marker}")
    lines += [
        "",
        "Pick the highest limit that lets no strangers in, with some margin below the closest pair.",
        "Photos from the door camera give the most realistic numbers; enroll with Capture where you can.",
    ]
    return "\n".join(lines)
