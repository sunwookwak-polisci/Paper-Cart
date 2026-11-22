"""Reading totals and CSV downloads for the active library's local calendar."""

from __future__ import annotations

import calendar
import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from paper_cart.db import connect


@dataclass(frozen=True)
class PaperActivity:
    doi: str
    title: str
    authors: str
    journal: str
    url: str
    at_utc: str
    local_date: str


@dataclass(frozen=True)
class Insights:
    unit: str
    period: str
    label: str
    counts: dict[date, int]
    selected: date | None
    papers: list[PaperActivity]
    activity: str
    current_streak: int
    longest_streak: int


def _period_bounds(period: str) -> tuple[date, date, str]:
    if "-" in period:
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


def _streaks(days: list[date], today: date) -> tuple[int, int]:
    """Distinct local activity dates in ascending order, across the whole library."""
    run = longest = 0
    last = None
    for day in days:
        if day > today:
            break
        run = run + 1 if last and (day - last).days == 1 else 1
        longest = max(longest, run)
        last = day
    current = run if last and (today - last).days <= 1 else 0
    return current, longest


def reading_insights(db_path: Path, unit: str, period: str, selected: str = "",
                     activity: str = "finished") -> Insights:
    today = date.today()
    if unit not in ("day", "month"):
        raise ValueError("Choose daily or monthly totals.")
    period = period or ("recent" if unit == "day" else str(today.year))
    if unit == "month" and period.isascii() and period.isdigit():
        period = period.zfill(4)
    all_time = period == "all"
    columns = {"sorted": "first_sorted_at", "started": "first_started_at", "finished": "first_completed_at"}
    if activity not in columns:
        raise ValueError("Choose sorted, started, or finished papers.")
    stamp = columns[activity]
    local_date = f"date({stamp}, 'localtime')"
    statement = f"""
        SELECT doi, title, authors, journal_title AS journal, url,
               {stamp} AS at_utc, {local_date} AS local_date
        FROM papers WHERE {stamp} IS NOT NULL
    """
    params = ()
    if not all_time:
        try:
            if period == "recent":
                start, end, label = today - timedelta(days=364), today, "Last 365 days"
            else:
                start, end, label = _period_bounds(period)
        except ValueError:
            raise ValueError("Choose a valid month or year.") from None
        statement += f" AND {local_date} BETWEEN ? AND ?"
        params = (start.isoformat(), end.isoformat())
    statement += f" ORDER BY {stamp} DESC, doi"
    with connect(db_path) as connection:
        connection.execute("BEGIN")
        papers = [PaperActivity(**row) for row in connection.execute(statement, params)]
        dates = connection.execute(
            f"SELECT DISTINCT {local_date} AS day FROM papers WHERE {stamp} IS NOT NULL ORDER BY day"
        )
        current, longest = _streaks([date.fromisoformat(row["day"]) for row in dates], today)

    if all_time:
        label = "All time"
        start = date.fromisoformat(papers[-1].local_date) if papers else today
        end = max(today, date.fromisoformat(papers[0].local_date)) if papers else today
    if unit == "day":
        periods = (start + timedelta(days=n) for n in range((end - start).days + 1))
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
        bucket = date.fromisoformat(paper.local_date)
        if unit == "month":
            bucket = bucket.replace(day=1)
        counts[bucket] += 1
        if selected_date is None or bucket == selected_date:
            visible.append(paper)
    return Insights(unit, period, label, counts, selected_date, visible, activity, current, longest)


def _csv_text(value: str) -> str:
    # Spreadsheet apps may evaluate metadata beginning with a formula character.
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def insights_csv(report: Insights, *, totals: bool) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    if totals:
        writer.writerow(("period_start", "period_unit", f"papers_{report.activity}"))
        for start, count in report.counts.items():
            writer.writerow((start, report.unit, count))
    else:
        event = "completed" if report.activity == "finished" else report.activity
        writer.writerow(("doi", "title", "authors", "journal", "url",
                         f"{event}_at_utc", f"{event}_date_local"))
        for paper in report.papers:
            metadata = (paper.doi, paper.title, paper.authors, paper.journal, paper.url)
            writer.writerow([*map(_csv_text, metadata), paper.at_utc, paper.local_date])
    return output.getvalue().encode("utf-8-sig")
