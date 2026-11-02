"""Download abstracts for recent issues without changing the library."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx

from paper_cart.crossref import CrossrefError, IssueGroup, user_agent
from paper_cart.db import Journal

MAX_ISSUES = 30
_SLUG = re.compile(r"[^a-z0-9]+")


class ExportCancelled(Exception):
    """Raised from a progress callback to stop an export early."""


# Called with (journal index, share of that journal done from 0 to 1, journal title).
ProgressCallback = Callable[[int, float, str], None]


@dataclass(frozen=True)
class JournalExport:
    title: str
    groups: tuple[IssueGroup, ...]
    error: str | None = None


def export_filename(journals: Sequence[Journal]) -> str:
    if len(journals) == 1:
        slug = _SLUG.sub("-", journals[0].title.casefold()).strip("-") or "journal"
        return f"{slug}-abstracts.md"
    return "journal-abstracts.md"


def format_abstract_export(exports: Sequence[JournalExport]) -> str:
    blocks: list[str] = []
    errors = [item.error for item in exports if item.error]
    if errors:
        blocks.append("\n\n".join(f"> {_md_inline(error)}" for error in errors))
    for item in exports:
        if not item.groups:
            continue
        lines = [f"# {_md_inline(item.title)}"]
        for group in item.groups:
            heading = group.label
            if group.date:
                heading = f"{heading} ({group.date})"
            lines.append("")
            lines.append(f"## {_md_inline(heading)}")
            for paper in group.papers:
                lines.append("")
                lines.append(f"### [{_md_link_text(paper.title)}]({paper.url})")
                if paper.authors:
                    lines.append("")
                    lines.append(f"*{_md_inline(paper.authors)}*")
                lines.append("")
                lines.append(_md_paragraph(paper.abstract) or "*No abstract in Crossref.*")
        blocks.append("\n".join(lines).rstrip())
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def _md_inline(value: str) -> str:
    return " ".join(value.split())


def _md_link_text(value: str) -> str:
    return _md_inline(value).replace("[", "\\[").replace("]", "\\]")


def _md_paragraph(value: str | None) -> str:
    if not value:
        return ""
    return "\n\n".join(part for part in (chunk.strip() for chunk in value.split("\n\n")) if part)


def export_journal_abstracts(
    journals: Sequence[Journal],
    issue_count: int,
    *,
    fetch: Callable[..., list[IssueGroup]],
    mailto: str | None,
    on_progress: ProgressCallback | None = None,
) -> list[JournalExport]:
    """Fetch each journal's recent issues.

    `on_progress` hears about each journal as it starts and as Crossref pages
    arrive. It may raise ExportCancelled to stop; that propagates to the caller.
    """
    headers = {"User-Agent": user_agent(mailto), "Accept": "application/json"}
    results: list[JournalExport] = []
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for index, journal in enumerate(journals):

            def report(share: float, index: int = index, title: str = journal.title) -> None:
                if on_progress is not None:
                    on_progress(index, min(max(share, 0.0), 1.0), title)

            report(0.0)
            try:
                groups = fetch(
                    journal.issns,
                    issue_count,
                    mailto=mailto,
                    client=client,
                    progress=report,
                )
            except CrossrefError as exc:
                results.append(
                    JournalExport(title=journal.title, groups=(), error=f"{journal.title}: {exc}")
                )
                continue
            except httpx.HTTPError:
                results.append(
                    JournalExport(
                        title=journal.title,
                        groups=(),
                        error=f"{journal.title}: Crossref could not be reached.",
                    )
                )
                continue
            results.append(JournalExport(title=journal.title, groups=tuple(groups)))
    return results


class ExportJob:
    """One background export, polled by the Journals page while it runs.

    The worker thread reports progress through `progress()`; request threads read
    `snapshot()`. States: running, ready, empty, cancelled, failed.
    """

    def __init__(self, journals: Sequence[Journal]) -> None:
        self.id = uuid.uuid4().hex
        self.titles = tuple(journal.title for journal in journals)
        self.filename = export_filename(journals)
        self.state = "running"
        self.text = ""
        self.downloaded = False
        self._index = 0
        self._share = 0.0
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    @property
    def pending(self) -> bool:
        """True while the page should still show this job: running or not yet downloaded."""
        return self.state == "running" or (self.state == "ready" and not self.downloaded)

    def progress(self, index: int, share: float, title: str) -> None:
        if self._cancel.is_set():
            raise ExportCancelled
        with self._lock:
            self._index = index
            self._share = share

    def cancel(self) -> None:
        self._cancel.set()

    def finish(self, text: str) -> None:
        with self._lock:
            self.text = text
            self.state = "ready" if text else "empty"

    def stop(self, state: str) -> None:
        with self._lock:
            self.state = state

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            state = self.state
            index = self._index
            share = self._share
        total = len(self.titles)
        cancelling = state == "running" and self._cancel.is_set()
        if state == "running":
            percent = min(99, int(100 * (index + share) / total)) if total else 0
        else:
            percent = 100 if state == "ready" else 0
        if cancelling:
            message = "Cancelling…"
        elif state == "running" and total > 1:
            message = f"Exporting abstracts… {index} of {total} journals done"
        elif state == "running":
            message = "Exporting abstracts…"
        else:
            message = _JOB_MESSAGES[state]
        current = self.titles[index] if state == "running" and index < total else None
        return {
            "id": self.id,
            "state": state,
            "percent": percent,
            "message": message,
            "current": current,
            "cancelling": cancelling,
            "filename": self.filename if state == "ready" else None,
            "download": f"/journals/export/{self.id}/download" if state == "ready" else None,
        }


_JOB_MESSAGES = {
    "ready": "Export ready.",
    "empty": "No recent issues were found for those journals.",
    "cancelled": "Export cancelled.",
    "failed": "The export stopped because of an error. Try again.",
}
