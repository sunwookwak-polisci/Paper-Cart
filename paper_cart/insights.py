"""Reading totals and CSV downloads for the active library's local calendar."""

from __future__ import annotations

import calendar
import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from paper_cart.db import connect


@dataclass(frozen=True)
class Completion:
    doi: str
    title: str
    authors: str
    journal: str
    url: str
    completed_at_utc: str
    completed_date_local: str


@dataclass(frozen=True)
class Insights:
    unit: str
    period: str
    label: str
    counts: dict[date, int]
    selected: date | None
    papers: list[Completion]


def _period_bounds(unit: str, period: str) -> tuple[date, date, str]:
    if unit == "day":
        start = date.fromisoformat(period + "-01")
        if start.isoformat()[:7] != period:
            raise ValueError
        end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        return start, end, start.strftime("%B %Y")
    if len(period) > 4 or not period.isascii() or not period.isdigit():
        raise ValueError
    year = int(period)
    return date(year, 1, 1), date(year, 12, 31), period


def _months(start: date, end: date):
    for year in range(start.year, end.year + 1):
        first = start.month if year == start.year else 1
        last = end.month if year == end.year else 12
        for month in range(first, last + 1):
            yield date(year, month, 1)


def reading_insights(db_path: Path, unit: str, period: str, selected: str = "") -> Insights:
    today = date.today()
    if unit not in ("day", "month"):
        raise ValueError("Choose daily or monthly totals.")
    period = period or (today.isoformat()[:7] if unit == "day" else str(today.year))
    if unit == "month" and period.isascii() and period.isdigit():
        period = period.zfill(4)
    all_time = unit == "month" and period == "all"
    statement = """
        SELECT doi, title, authors, journal_title AS journal, url,
               first_completed_at AS completed_at_utc,
               date(first_completed_at, 'localtime') AS completed_date_local
        FROM papers WHERE first_completed_at IS NOT NULL
    """
    params = ()
    if not all_time:
        try:
            start, end, label = _period_bounds(unit, period)
        except ValueError:
            raise ValueError("Choose a valid month or year.") from None
        statement += " AND date(first_completed_at, 'localtime') BETWEEN ? AND ?"
        params = (start.isoformat(), end.isoformat())
    statement += " ORDER BY first_completed_at DESC, doi"
    with connect(db_path) as connection:
        papers = [Completion(**row) for row in connection.execute(statement, params)]

    if all_time:
        label = "All time"
        start = date.fromisoformat(papers[-1].completed_date_local) if papers else today
        end = max(today, date.fromisoformat(papers[0].completed_date_local)) if papers else today
    if unit == "day":
        periods = (start.replace(day=day) for day in range(1, end.day + 1))
    else:
        periods = _months(start, end)
    counts = dict.fromkeys(periods, 0)
    try:
        selected_date = date.fromisoformat(selected) if selected else None
    except ValueError:
        raise ValueError("Choose a date from the chart.") from None
    if selected_date not in counts:
        selected_date = None
    visible = []
    for paper in papers:
        bucket = date.fromisoformat(paper.completed_date_local)
        if unit == "month":
            bucket = bucket.replace(day=1)
        counts[bucket] += 1
        if selected_date is None or bucket == selected_date:
            visible.append(paper)
    return Insights(unit, period, label, counts, selected_date, visible)


def _csv_text(value: str) -> str:
    # Spreadsheet apps may evaluate metadata beginning with a formula character.
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def insights_csv(report: Insights, *, totals: bool) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    if totals:
        writer.writerow(("period_start", "period_unit", "papers_finished"))
        for start, count in report.counts.items():
            writer.writerow((start, report.unit, count))
    else:
        writer.writerow(("doi", "title", "authors", "journal", "url",
                         "completed_at_utc", "completed_date_local"))
        for paper in report.papers:
            metadata = (paper.doi, paper.title, paper.authors, paper.journal, paper.url)
            writer.writerow([*map(_csv_text, metadata), paper.completed_at_utc,
                             paper.completed_date_local])
    return output.getvalue().encode("utf-8-sig")
