"""SQLite library. Reading status is never overwritten by a refresh."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

STATUSES = ("new", "read_later", "reading", "done", "dismissed", "removed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS journals (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    primary_issn TEXT NOT NULL UNIQUE,
    issns TEXT NOT NULL,
    publisher TEXT NOT NULL DEFAULT '',
    subscribed INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    sort_rank INTEGER
);

CREATE TABLE IF NOT EXISTS cart_items (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL DEFAULT '',
    issns TEXT NOT NULL,
    primary_issn TEXT NOT NULL UNIQUE,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    doi TEXT PRIMARY KEY,
    journal_id INTEGER NOT NULL REFERENCES journals(id),
    journal_title TEXT NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '',
    abstract TEXT,
    published_date TEXT,
    url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    status_updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS papers_journal ON papers(journal_id);
"""


@dataclass(frozen=True)
class Journal:
    id: int
    title: str
    primary_issn: str
    issns: tuple[str, ...]
    publisher: str
    subscribed: bool
    last_checked_at: str | None
    sort_rank: int | None


@dataclass(frozen=True)
class CartItem:
    id: int
    title: str
    publisher: str
    issns: tuple[str, ...]


@dataclass(frozen=True)
class Paper:
    doi: str
    journal_title: str
    title: str
    authors: str
    abstract: str | None
    published_date: str | None
    url: str
    status: str


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class LibraryUnavailable(Exception):
    """The library file was renamed or removed before this request could open it."""


_GATE = threading.RLock()


def library_lock():
    """Serialize opens of a library file with a swap or rename of that file."""
    return _GATE


@contextmanager
def connect(db_path: Path, *, create: bool = False) -> Iterator[sqlite3.Connection]:
    with _GATE:
        path = Path(db_path)
        if not create and not path.is_file():
            raise LibraryUnavailable(str(path))
        try:
            if create:
                connection = sqlite3.connect(path)
            else:
                connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)
        except sqlite3.OperationalError as exc:
            if not create and not path.is_file():
                raise LibraryUnavailable(str(path)) from exc
            raise
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path, create=True) as connection:
        connection.executescript(SCHEMA)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(journals)")}
        if "sort_rank" not in columns:
            connection.execute("ALTER TABLE journals ADD COLUMN sort_rank INTEGER")


def subscribe_journal(
    db_path: Path,
    *,
    title: str,
    issns: tuple[str, ...],
    publisher: str,
) -> int:
    primary = issns[0]
    payload = json.dumps(list(issns))
    with connect(db_path) as connection:
        existing = connection.execute(
            "SELECT id FROM journals WHERE primary_issn = ?",
            (primary,),
        ).fetchone()
        if existing is not None:
            connection.execute(
                """
                UPDATE journals
                SET title = ?, issns = ?, publisher = ?, subscribed = 1
                WHERE id = ?
                """,
                (title, payload, publisher, existing["id"]),
            )
            return int(existing["id"])
        cursor = connection.execute(
            """
            INSERT INTO journals
                (title, primary_issn, issns, publisher, subscribed, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (title, primary, payload, publisher, utcnow()),
        )
        return int(cursor.lastrowid)


def unsubscribe_journal(db_path: Path, journal_id: int) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "UPDATE journals SET subscribed = 0 WHERE id = ?",
            (journal_id,),
        )


def get_journal(db_path: Path, journal_id: int) -> Journal | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM journals WHERE id = ?",
            (journal_id,),
        ).fetchone()
    if row is None:
        return None
    return _journal_from_row(row)


def list_journals(db_path: Path, *, subscribed_only: bool = False) -> list[Journal]:
    query = "SELECT * FROM journals"
    if subscribed_only:
        query += " WHERE subscribed = 1"
    query += " ORDER BY title COLLATE NOCASE"
    with connect(db_path) as connection:
        rows = connection.execute(query).fetchall()
    return [_journal_from_row(row) for row in rows]


def upsert_papers(
    db_path: Path,
    journal_id: int,
    journal_title: str,
    papers: list,
) -> int:
    """Insert new papers and refresh metadata. Existing reading status stays."""
    added = 0
    now = utcnow()
    with connect(db_path) as connection:
        for paper in papers:
            existing = connection.execute(
                "SELECT 1 FROM papers WHERE doi = ?",
                (paper.doi,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO papers (
                        doi, journal_id, journal_title, title, authors, abstract,
                        published_date, url, first_seen_at, status, status_updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
                    """,
                    (
                        paper.doi,
                        journal_id,
                        journal_title,
                        paper.title,
                        paper.authors,
                        paper.abstract,
                        paper.published_date,
                        paper.url,
                        now,
                        now,
                    ),
                )
                added += 1
                continue
            connection.execute(
                """
                UPDATE papers SET
                    title = ?,
                    authors = ?,
                    abstract = COALESCE(?, abstract),
                    published_date = COALESCE(?, published_date),
                    url = ?
                WHERE doi = ?
                """,
                (
                    paper.title,
                    paper.authors,
                    paper.abstract,
                    paper.published_date,
                    paper.url,
                    paper.doi,
                ),
            )
    return added


def mark_checked(db_path: Path, journal_id: int, when: str | None = None) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "UPDATE journals SET last_checked_at = ? WHERE id = ?",
            (when or utcnow(), journal_id),
        )


def set_status(db_path: Path, doi: str, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError(status)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM papers WHERE doi = ?",
            (doi,),
        ).fetchone()
        if row is None:
            return False
        if row["status"] == status:
            return True
        if status == "removed" and row["status"] != "dismissed":
            raise ValueError("Only dismissed papers can be removed.")
        connection.execute(
            """
            UPDATE papers
            SET status = ?, status_updated_at = ?
            WHERE doi = ?
            """,
            (status, utcnow(), doi),
        )
    return True


def set_statuses(db_path: Path, dois: Sequence[str], status: str) -> int:
    """Move several papers at once and return how many were found.

    Removal still applies only to dismissed papers.
    """
    if status not in STATUSES:
        raise ValueError(status)
    unique = list(dict.fromkeys(dois))
    if not unique:
        return 0
    placeholders = ", ".join("?" for _ in unique)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT doi, status FROM papers WHERE doi IN ({placeholders})",
            unique,
        ).fetchall()
        if status == "removed" and any(row["status"] not in {"dismissed", "removed"} for row in rows):
            raise ValueError("Only dismissed papers can be removed.")
        changing = [row["doi"] for row in rows if row["status"] != status]
        if changing:
            connection.executemany(
                """
                UPDATE papers
                SET status = ?, status_updated_at = ?
                WHERE doi = ?
                """,
                [(status, utcnow(), doi) for doi in changing],
            )
    return len(rows)


def list_papers(db_path: Path, status: str, *, query: str = "") -> list[Paper]:
    statement = "SELECT * FROM papers WHERE status = ?"
    parameters: list[object] = [status]
    for term in query.split():
        like = _like_term(term)
        statement += """
            AND (
                title LIKE ? ESCAPE '\\'
                OR authors LIKE ? ESCAPE '\\'
                OR IFNULL(abstract, '') LIKE ? ESCAPE '\\'
                OR journal_title LIKE ? ESCAPE '\\'
                OR doi LIKE ? ESCAPE '\\'
            )
        """
        parameters.extend((like, like, like, like, like))
    statement += """
        ORDER BY published_date IS NULL, published_date DESC,
                 first_seen_at DESC, title COLLATE NOCASE
    """
    with connect(db_path) as connection:
        rows = connection.execute(statement, parameters).fetchall()
    return [
        Paper(
            doi=row["doi"],
            journal_title=row["journal_title"],
            title=row["title"],
            authors=row["authors"],
            abstract=row["abstract"],
            published_date=row["published_date"],
            url=row["url"],
            status=row["status"],
        )
        for row in rows
    ]


def status_counts(db_path: Path) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS n FROM papers GROUP BY status"
        ).fetchall()
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] = int(row["n"])
    return counts


def get_setting(db_path: Path, key: str, default: str) -> str:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return default
    return str(row["value"])


def set_setting(db_path: Path, key: str, value: str) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def add_cart_item(
    db_path: Path,
    *,
    title: str,
    issns: tuple[str, ...],
    publisher: str,
) -> None:
    primary = issns[0]
    payload = json.dumps(list(issns))
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO cart_items (title, publisher, issns, primary_issn, added_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(primary_issn) DO UPDATE SET
                title = excluded.title,
                publisher = excluded.publisher,
                issns = excluded.issns
            """,
            (title, publisher, payload, primary, utcnow()),
        )


def list_cart(db_path: Path) -> list[CartItem]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM cart_items ORDER BY added_at, id"
        ).fetchall()
    items: list[CartItem] = []
    for row in rows:
        stored = json.loads(row["issns"])
        items.append(
            CartItem(
                id=int(row["id"]),
                title=row["title"],
                publisher=row["publisher"],
                issns=tuple(str(issn) for issn in stored),
            )
        )
    return items


def remove_cart_item(db_path: Path, item_id: int) -> None:
    with connect(db_path) as connection:
        connection.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))


def clear_cart(db_path: Path) -> None:
    with connect(db_path) as connection:
        connection.execute("DELETE FROM cart_items")


def list_journals_by_rank(db_path: Path) -> list[Journal]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM journals
            WHERE subscribed = 1
            ORDER BY sort_rank IS NULL, sort_rank ASC, title COLLATE NOCASE
            """
        ).fetchall()
    return [_journal_from_row(row) for row in rows]


def ensure_custom_order(db_path: Path) -> None:
    """Give unranked subscribed journals a rank, using newest paper date."""
    journals = list_journals(db_path, subscribed_only=True)
    unranked = [journal for journal in journals if journal.sort_rank is None]
    if not unranked:
        return
    latest = _latest_dates(db_path)
    unranked.sort(key=lambda journal: journal.title.casefold())
    dated = [journal for journal in unranked if latest.get(journal.id)]
    undated = [journal for journal in unranked if not latest.get(journal.id)]
    dated.sort(key=lambda journal: latest[journal.id], reverse=True)
    unranked = dated + undated
    ranked = [journal.sort_rank for journal in journals if journal.sort_rank is not None]
    start = 0 if not ranked else max(ranked) + 1
    with connect(db_path) as connection:
        for offset, journal in enumerate(unranked):
            connection.execute(
                "UPDATE journals SET sort_rank = ? WHERE id = ?",
                (start + offset, journal.id),
            )


def set_journal_order(db_path: Path, journal_ids: list[int]) -> None:
    if not journal_ids:
        return
    journals = list_journals_by_rank(db_path)
    known = {journal.id for journal in journals}
    ordered: list[int] = []
    seen: set[int] = set()
    for journal_id in journal_ids:
        if journal_id in known and journal_id not in seen:
            ordered.append(journal_id)
            seen.add(journal_id)
    for journal in journals:
        if journal.id not in seen:
            ordered.append(journal.id)
    with connect(db_path) as connection:
        for position, journal_id in enumerate(ordered):
            connection.execute(
                "UPDATE journals SET sort_rank = ? WHERE id = ?",
                (position, journal_id),
            )


def move_journal(db_path: Path, journal_id: int, direction: int) -> None:
    if direction not in (-1, 1):
        return
    journals = list_journals_by_rank(db_path)
    index = next((i for i, journal in enumerate(journals) if journal.id == journal_id), None)
    if index is None:
        return
    target = index + direction
    if target < 0 or target >= len(journals):
        return
    with connect(db_path) as connection:
        for position, journal in enumerate(journals):
            connection.execute(
                "UPDATE journals SET sort_rank = ? WHERE id = ?",
                (position, journal.id),
            )
        current = journals[index]
        neighbor = journals[target]
        connection.execute(
            "UPDATE journals SET sort_rank = ? WHERE id = ?",
            (target, current.id),
        )
        connection.execute(
            "UPDATE journals SET sort_rank = ? WHERE id = ?",
            (index, neighbor.id),
        )


def _latest_dates(db_path: Path) -> dict[int, str]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT journal_id, MAX(published_date) AS latest
            FROM papers
            WHERE published_date IS NOT NULL
            GROUP BY journal_id
            """
        ).fetchall()
    return {int(row["journal_id"]): str(row["latest"]) for row in rows}


def _like_term(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _journal_from_row(row: sqlite3.Row) -> Journal:
    stored = json.loads(row["issns"])
    issns = tuple(str(issn) for issn in stored)
    return Journal(
        id=int(row["id"]),
        title=row["title"],
        primary_issn=row["primary_issn"],
        issns=issns,
        publisher=row["publisher"],
        subscribed=bool(row["subscribed"]),
        last_checked_at=row["last_checked_at"],
        sort_rank=None if row["sort_rank"] is None else int(row["sort_rank"]),
    )
