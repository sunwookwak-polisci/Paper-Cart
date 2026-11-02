"""Fetch newly indexed papers without changing reading status."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from paper_cart.crossref import CrossrefError, PaperHit, user_agent
from paper_cart.db import Journal, mark_checked, upsert_papers, utcnow


@dataclass
class RefreshReport:
    added: int = 0
    checked: int = 0
    errors: list[str] = field(default_factory=list)


FIRST_LOOK_BACK = timedelta(days=30)
# Crossref can list a paper hours or days after the date it gives it, so each
# check reaches back past the last one. A paper seen twice keeps its list.
OVERLAP = timedelta(days=7)


def window_start(last_checked_at: str | None, today: date) -> date:
    if last_checked_at is None:
        return today - FIRST_LOOK_BACK
    return datetime.fromisoformat(last_checked_at).date() - OVERLAP


def refresh_journals(
    db_path: Path,
    journals: Sequence[Journal],
    *,
    fetch: Callable[..., list[PaperHit]],
    mailto: str | None,
    today: date | None = None,
) -> RefreshReport:
    today = today or date.today()
    report = RefreshReport()
    headers = {"User-Agent": user_agent(mailto), "Accept": "application/json"}
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for journal in journals:
            start = window_start(journal.last_checked_at, today)
            # Record when this check began, so a long fetch can't skip the hours it took.
            began = utcnow()
            try:
                papers = fetch(journal.issns, start, mailto=mailto, client=client)
            except CrossrefError as exc:
                report.errors.append(f"{journal.title}: {exc}")
                continue
            except httpx.HTTPError:
                report.errors.append(f"{journal.title}: Crossref could not be reached.")
                continue
            except json.JSONDecodeError:
                report.errors.append(f"{journal.title}: Crossref returned an unreadable response.")
                continue
            report.added += upsert_papers(db_path, journal.id, journal.title, papers)
            mark_checked(db_path, journal.id, began)
            report.checked += 1
    return report
