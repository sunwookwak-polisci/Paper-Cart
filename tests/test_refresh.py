from datetime import date

from paper_cart.crossref import PaperHit
from paper_cart.db import init_db, list_journals, list_papers, set_status, subscribe_journal
from paper_cart.refresh import refresh_journals, window_start


def test_window_is_longer_on_the_first_check():
    today = date(2026, 9, 30)
    assert window_start(None, today) == date(2026, 8, 31)
    assert window_start("2026-09-20T00:00:00+00:00", today) == date(2026, 9, 16)


def test_second_refresh_keeps_status_and_shortens_the_window(tmp_path):
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
    second = refresh_journals(db_path, journals, fetch=fetch, mailto=None, today=today)
    assert second.added == 0
    assert [paper.status for paper in list_papers(db_path, "read_later")] == ["read_later"]
    assert list_papers(db_path, "new") == []
    assert starts == [date(2026, 8, 31), date(2026, 9, 16)]


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


def _paper() -> PaperHit:
    return PaperHit(
        doi="10.1000/example",
        title="A real paper",
        authors="Ada Lovelace",
        abstract=None,
        published_date="2026-09-01",
        url="https://doi.org/10.1000/example",
    )
