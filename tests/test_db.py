import sqlite3

import pytest

from paper_cart.crossref import PaperHit
from paper_cart.db import (
    ensure_custom_order,
    init_db,
    list_journals,
    list_journals_by_rank,
    list_papers,
    move_journal,
    set_journal_order,
    set_status,
    subscribe_journal,
    upsert_papers,
)


def test_upsert_preserves_reading_status(tmp_path):
    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    journal_id = subscribe_journal(
        db_path,
        title="Example Journal",
        issns=("1234-5678",),
        publisher="Example Press",
    )
    original = _paper("A real paper")
    assert upsert_papers(db_path, journal_id, "Example Journal", [original]) == 1
    assert set_status(db_path, original.doi, "reading")
    revised = _paper("A real paper, revised")
    assert upsert_papers(db_path, journal_id, "Example Journal", [revised]) == 0

    reading = list_papers(db_path, "reading")
    assert len(reading) == 1
    assert reading[0].title == "A real paper, revised"
    assert reading[0].status == "reading"
    assert list_papers(db_path, "new") == []


def test_remove_only_from_dismissed(tmp_path):
    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    journal_id = subscribe_journal(
        db_path,
        title="Example Journal",
        issns=("1234-5678",),
        publisher="",
    )
    paper = _paper("A real paper")
    upsert_papers(db_path, journal_id, "Example Journal", [paper])
    with pytest.raises(ValueError, match="dismissed"):
        set_status(db_path, paper.doi, "removed")
    assert list_papers(db_path, "new")[0].doi == paper.doi
    assert set_status(db_path, paper.doi, "dismissed")
    assert set_status(db_path, paper.doi, "removed")
    assert [item.doi for item in list_papers(db_path, "removed")] == [paper.doi]
    assert list_papers(db_path, "dismissed") == []
    assert set_status(db_path, paper.doi, "done")
    assert list_papers(db_path, "done")[0].status == "done"


def test_same_status_click_keeps_the_paper(tmp_path):
    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    journal_id = subscribe_journal(
        db_path,
        title="Example Journal",
        issns=("1234-5678",),
        publisher="",
    )
    paper = _paper("A real paper")
    upsert_papers(db_path, journal_id, "Example Journal", [paper])
    assert set_status(db_path, paper.doi, "new")
    assert list_papers(db_path, "new")[0].doi == paper.doi
    assert not set_status(db_path, "10.1000/missing", "done")


def test_keyword_search_escapes_like_wildcards(tmp_path):
    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    journal_id = subscribe_journal(
        db_path,
        title="Example Journal",
        issns=("1234-5678",),
        publisher="",
    )
    upsert_papers(
        db_path,
        journal_id,
        "Example Journal",
        [
            PaperHit(
                doi="10.1000/percent",
                title="100% complete",
                authors="Ada Lovelace",
                abstract="Hello",
                published_date="2026-09-01",
                url="https://doi.org/10.1000/percent",
            ),
            PaperHit(
                doi="10.1000/other",
                title="A different paper",
                authors="Grace Hopper",
                abstract="Notes",
                published_date="2026-08-01",
                url="https://doi.org/10.1000/other",
            ),
        ],
    )
    percent = list_papers(db_path, "new", query="%")
    assert [paper.title for paper in percent] == ["100% complete"]
    assert list_papers(db_path, "new", query="_") == []
    assert [paper.title for paper in list_papers(db_path, "new", query="100%")] == ["100% complete"]
    assert [paper.title for paper in list_papers(db_path, "new", query="ada complete")] == [
        "100% complete"
    ]
    assert list_papers(db_path, "reading", query="complete") == []


def test_custom_order_follows_latest_paper_then_moves(tmp_path):
    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    alpha = subscribe_journal(
        db_path,
        title="Alpha Journal",
        issns=("1111-1111",),
        publisher="",
    )
    beta = subscribe_journal(
        db_path,
        title="Beta Journal",
        issns=("2222-2222",),
        publisher="",
    )
    upsert_papers(
        db_path,
        alpha,
        "Alpha Journal",
        [
            PaperHit(
                doi="10.1000/old",
                title="Older paper",
                authors="",
                abstract=None,
                published_date="2026-01-01",
                url="https://doi.org/10.1000/old",
            )
        ],
    )
    upsert_papers(
        db_path,
        beta,
        "Beta Journal",
        [
            PaperHit(
                doi="10.1000/new",
                title="Newer paper",
                authors="",
                abstract=None,
                published_date="2026-08-01",
                url="https://doi.org/10.1000/new",
            )
        ],
    )
    ensure_custom_order(db_path)
    assert [journal.title for journal in list_journals_by_rank(db_path)] == [
        "Beta Journal",
        "Alpha Journal",
    ]
    move_journal(db_path, alpha, -1)
    assert [journal.title for journal in list_journals_by_rank(db_path)] == [
        "Alpha Journal",
        "Beta Journal",
    ]
    move_journal(db_path, alpha, -1)
    assert [journal.title for journal in list_journals_by_rank(db_path)] == [
        "Alpha Journal",
        "Beta Journal",
    ]
    set_journal_order(db_path, [beta, alpha])
    assert [journal.title for journal in list_journals_by_rank(db_path)] == [
        "Beta Journal",
        "Alpha Journal",
    ]


def test_init_adds_sort_rank_to_existing_library(tmp_path):
    db_path = tmp_path / "library.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE journals (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            primary_issn TEXT NOT NULL UNIQUE,
            issns TEXT NOT NULL,
            publisher TEXT NOT NULL DEFAULT '',
            subscribed INTEGER NOT NULL DEFAULT 1,
            last_checked_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO journals (title, primary_issn, issns, publisher, created_at)
        VALUES ('Example Journal', '1234-5678', '["1234-5678"]', '', '2026-01-01T00:00:00+00:00')
        """
    )
    connection.commit()
    connection.close()
    init_db(db_path)
    journals = list_journals(db_path)
    assert journals[0].title == "Example Journal"
    assert journals[0].sort_rank is None


def _paper(title: str) -> PaperHit:
    return PaperHit(
        doi="10.1000/example",
        title=title,
        authors="Ada Lovelace",
        abstract="Hello",
        published_date="2026-09-01",
        url="https://doi.org/10.1000/example",
    )
