"""Download abstracts for recent issues without changing the library."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx

from paper_cart.crossref import CrossrefError, IssueGroup, user_agent
from paper_cart.db import Journal

MAX_ISSUES = 30
_SLUG = re.compile(r"[^a-z0-9]+")


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
) -> list[JournalExport]:
    headers = {"User-Agent": user_agent(mailto), "Accept": "application/json"}
    results: list[JournalExport] = []
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for journal in journals:
            try:
                groups = fetch(
                    journal.issns,
                    issue_count,
                    mailto=mailto,
                    client=client,
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
