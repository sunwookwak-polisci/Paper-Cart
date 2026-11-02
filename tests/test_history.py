import pytest

from paper_cart.crossref import PaperHit
from paper_cart.db import init_db, list_papers, move_papers, replay_changes, subscribe_journal, upsert_papers
from paper_cart.history import History


def _library(tmp_path, count=3, name="library.sqlite"):
    db_path = tmp_path / name
    init_db(db_path)
    journal_id = subscribe_journal(db_path, title="Example Journal", issns=("1234-5678",), publisher="")
    upsert_papers(
        db_path,
        journal_id,
        "Example Journal",
        [
            PaperHit(
                doi=f"10.1000/p{n}",
                title=f"Paper {n}",
                authors="",
                abstract=None,
                published_date="2026-09-01",
                url=f"https://doi.org/10.1000/p{n}",
            )
            for n in range(count)
        ],
    )
    return db_path


def _dois(db_path, status):
    return sorted(paper.doi for paper in list_papers(db_path, status))


def test_move_papers_reports_only_real_changes(tmp_path):
    db_path = _library(tmp_path)
    found, changes = move_papers(db_path, ["10.1000/p0", "10.1000/missing"], "dismissed")
    assert found == 1
    assert [(c.doi, c.title, c.before, c.after) for c in changes] == [
        ("10.1000/p0", "Paper 0", "new", "dismissed")
    ]
    found, changes = move_papers(db_path, ["10.1000/p0"], "dismissed")
    assert (found, changes) == (1, [])


def test_replay_restores_status_and_timestamp_and_skips_later_choices(tmp_path):
    db_path = _library(tmp_path)
    _, first = move_papers(db_path, ["10.1000/p0"], "reading")
    _, changes = move_papers(db_path, ["10.1000/p0", "10.1000/p1"], "done")
    # p1 moved on since, so undoing the "done" step must leave it alone.
    move_papers(db_path, ["10.1000/p1"], "dismissed")
    applied = replay_changes(db_path, changes, undo=True)
    assert [change.doi for change in applied] == ["10.1000/p0"]
    assert _dois(db_path, "reading") == ["10.1000/p0"]
    assert _dois(db_path, "dismissed") == ["10.1000/p1"]
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        stamp = connection.execute(
            "SELECT status_updated_at FROM papers WHERE doi = '10.1000/p0'"
        ).fetchone()[0]
    assert stamp == first[0].after_at


def test_undo_and_redo_walk_the_steps(tmp_path):
    db_path = _library(tmp_path)
    history = History()
    assert history.labels(db_path) == ("", "")
    assert history.undo(db_path) is None

    history.record(db_path, move_papers(db_path, ["10.1000/p0"], "dismissed")[1])
    history.record(db_path, move_papers(db_path, ["10.1000/p1", "10.1000/p2"], "read_later")[1])
    assert history.labels(db_path) == ("moving 2 papers to Read later", "")

    assert history.undo(db_path).describe() == "moving 2 papers to Read later"
    assert _dois(db_path, "new") == ["10.1000/p1", "10.1000/p2"]
    assert history.labels(db_path) == ("dismissing “Paper 0”", "moving 2 papers to Read later")

    history.undo(db_path)
    assert _dois(db_path, "new") == ["10.1000/p0", "10.1000/p1", "10.1000/p2"]
    assert history.undo(db_path) is None

    history.redo(db_path)
    assert _dois(db_path, "dismissed") == ["10.1000/p0"]
    # A new move clears what was left to redo.
    history.record(db_path, move_papers(db_path, ["10.1000/p0"], "removed")[1])
    assert history.labels(db_path) == ("removing “Paper 0”", "")
    history.undo(db_path)
    assert _dois(db_path, "dismissed") == ["10.1000/p0"]


def test_undo_skips_steps_that_no_longer_apply(tmp_path):
    db_path = _library(tmp_path)
    history = History()
    history.record(db_path, move_papers(db_path, ["10.1000/p0"], "done")[1])
    history.record(db_path, move_papers(db_path, ["10.1000/p1"], "done")[1])
    move_papers(db_path, ["10.1000/p1"], "reading")  # changed outside history
    step = history.undo(db_path)
    assert step.describe() == "moving “Paper 0” to Done"
    assert _dois(db_path, "new") == ["10.1000/p0", "10.1000/p2"]


def test_history_is_kept_per_library_and_capped(tmp_path):
    first = _library(tmp_path)
    second = _library(tmp_path, name="other.sqlite")
    history = History(limit=2)
    for n in range(3):
        history.record(first, move_papers(first, [f"10.1000/p{n}"], "done")[1])
    assert history.undo(first) and history.undo(first)
    assert history.undo(first) is None
    assert _dois(first, "done") == ["10.1000/p0"]

    history.record(first, move_papers(first, ["10.1000/p1"], "done")[1])
    assert history.labels(second) == ("", "")
    assert history.labels(first) == ("", "")


@pytest.mark.parametrize(
    ("title", "label"),
    [
        ("A  short\ntitle", "moving “A short title” to New"),
        ("x" * 80, "moving “" + "x" * 59 + "…” to New"),
    ],
)
def test_labels_tidy_long_titles(tmp_path, title, label):
    from paper_cart.db import StatusChange
    from paper_cart.history import Step

    change = StatusChange("10.1000/x", title, "dismissed", "", "new", "")
    assert Step((change,)).describe() == label


def test_a_failed_undo_keeps_the_step(tmp_path):
    from paper_cart.db import LibraryUnavailable

    db_path = _library(tmp_path)
    history = History()
    _, changes = move_papers(db_path, ["10.1000/p0"], "done")
    history.record(db_path, changes)
    parked = tmp_path / "parked.sqlite"
    db_path.rename(parked)
    with pytest.raises(LibraryUnavailable):
        history.undo(db_path)
    parked.rename(db_path)
    assert history.labels(db_path)[0] == "moving “Paper 0” to Done"
    assert history.undo(db_path) is not None
    assert _dois(db_path, "new") == ["10.1000/p0", "10.1000/p1", "10.1000/p2"]
