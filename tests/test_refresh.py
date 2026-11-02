import sqlite3
from datetime import date, datetime, timedelta

from paper_cart.crossref import PaperHit
from paper_cart.db import init_db, list_journals, list_papers, set_status, subscribe_journal
from paper_cart.refresh import refresh_journals, window_start


def test_later_window_reaches_a_week_before_the_last_check():
    today = date(2026, 9, 30)
    assert window_start(None, today) == date(2026, 8, 31)
    assert window_start("2026-09-10T15:04:05+00:00", today) == date(2026, 9, 3)
    # A check just after midnight UTC still asks for papers Crossref dated the day before.
    assert window_start("2026-11-01T00:10:00+00:00", date(2026, 11, 2)) <= date(2026, 10, 31)
    # A long gap between launches leaves no hole.
    assert window_start("2026-06-01T09:00:00+00:00", today) == date(2026, 5, 25)


def test_second_refresh_keeps_status_and_starts_at_the_last_check(tmp_path):
    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    subscribe_journal(
        db_path,
        title="Example Journal",
        issns=("1234-5678", "8765-4321"),
        publisher="Example Press",
    )
    starts: list[date] = []

    def fetch(issns, start, *, mailto=None, client=None, pause=None):
        assert issns == ("1234-5678", "8765-4321")
        assert mailto is None
        starts.append(start)
        return [_paper()]

    today = date(2026, 9, 30)
    journals = list_journals(db_path, subscribed_only=True)
    first = refresh_journals(db_path, journals, fetch=fetch, mailto=None, today=today)
    assert first.added == 1
    assert first.checked == 1
    assert set_status(db_path, "10.1000/example", "read_later")

    journals = list_journals(db_path, subscribed_only=True)
    last_checked_at = journals[0].last_checked_at
    assert last_checked_at is not None
    second = refresh_journals(db_path, journals, fetch=fetch, mailto=None, today=today)
    assert second.added == 0
    assert [paper.status for paper in list_papers(db_path, "read_later")] == ["read_later"]
    assert list_papers(db_path, "new") == []
    assert starts == [
        date(2026, 8, 31),
        datetime.fromisoformat(last_checked_at).date() - timedelta(days=7),
    ]


def test_second_refresh_of_the_same_doi_keeps_status_and_does_not_insert_another_row(tmp_path):
    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    subscribe_journal(
        db_path,
        title="Example Journal",
        issns=("1234-5678",),
        publisher="Example Press",
    )
    seen: list[int] = []

    def fetch(issns, start, *, mailto=None, client=None, pause=None):
        seen.append(1)
        if len(seen) == 1:
            return [_paper()]
        return [_paper(title="A real paper, revised")]

    today = date(2026, 9, 30)
    journals = list_journals(db_path, subscribed_only=True)
    first = refresh_journals(db_path, journals, fetch=fetch, mailto=None, today=today)
    assert first.added == 1
    assert set_status(db_path, "10.1000/example", "read_later")

    journals = list_journals(db_path, subscribed_only=True)
    second = refresh_journals(db_path, journals, fetch=fetch, mailto=None, today=today)
    assert second.added == 0
    kept = list_papers(db_path, "read_later")
    assert [paper.title for paper in kept] == ["A real paper, revised"]
    assert [paper.status for paper in kept] == ["read_later"]
    assert list_papers(db_path, "new") == []
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT doi, status FROM papers").fetchall()
    assert rows == [("10.1000/example", "read_later")]


def test_a_failed_journal_is_not_marked_checked(tmp_path):
    from paper_cart.crossref import CrossrefError

    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    subscribe_journal(
        db_path,
        title="Example Journal",
        issns=("1234-5678",),
        publisher="",
    )

    def fetch(issns, start, *, mailto=None, client=None, pause=None):
        raise CrossrefError("Crossref returned 503.")

    journals = list_journals(db_path, subscribed_only=True)
    report = refresh_journals(
        db_path,
        journals,
        fetch=fetch,
        mailto=None,
        today=date(2026, 9, 30),
    )
    assert report.checked == 0
    assert report.errors == ["Example Journal: Crossref returned 503."]
    assert list_journals(db_path)[0].last_checked_at is None


def _paper(*, title: str = "A real paper") -> PaperHit:
    return PaperHit(
        doi="10.1000/example",
        title=title,
        authors="Ada Lovelace",
        abstract=None,
        published_date="2026-09-01",
        url="https://doi.org/10.1000/example",
    )
