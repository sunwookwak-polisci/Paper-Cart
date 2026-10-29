from paper_cart.crossref import IssueGroup, PaperHit
from paper_cart.db import Journal
from paper_cart.export import JournalExport, export_filename, format_abstract_export


def test_format_includes_missing_abstracts_and_skips_empty_journals():
    newest = _paper(
        "10.1000/new",
        "Newest paper",
        abstract="Hello from the abstract",
        volume="12",
        issue="4",
        published="2026-10-02",
    )
    older = _paper(
        "10.1000/old",
        "Older paper",
        abstract=None,
        volume="12",
        issue="3",
        published="2026-09-01",
        authors="",
    )
    text = format_abstract_export(
        [
            JournalExport(
                title="Example Journal",
                groups=(
                    IssueGroup(volume="12", issue="4", date="2026-10", papers=(newest,)),
                    IssueGroup(volume="12", issue="3", date="2026-09", papers=(older,)),
                ),
            ),
            JournalExport(
                title="Other Journal",
                groups=(),
                error="Other Journal: Crossref returned 503.",
            ),
        ]
    )
    assert text.startswith("> Other Journal: Crossref returned 503.\n")
    assert "# Example Journal" in text
    assert "## Volume 12, Issue 4 (2026-10)" in text
    assert "## Volume 12, Issue 3 (2026-09)" in text
    assert "### [Newest paper](https://doi.org/10.1000/new)" in text
    assert "*Ada Lovelace*" in text
    assert "Hello from the abstract" in text
    assert "### [Older paper](https://doi.org/10.1000/old)" in text
    assert "*No abstract in Crossref.*" in text
    assert text.index("Newest paper") < text.index("Older paper")


def test_format_escapes_brackets_in_markdown_titles():
    paper = _paper(
        "10.1000/brackets",
        "Notes [draft]",
        abstract="Body",
        volume="1",
        issue="1",
        published="2026-10-01",
    )
    text = format_abstract_export(
        [
            JournalExport(
                title="Example Journal",
                groups=(IssueGroup(volume="1", issue="1", date="2026-10", papers=(paper,)),),
            )
        ]
    )
    assert "### [Notes \\[draft\\]](https://doi.org/10.1000/brackets)" in text


def test_export_filename_uses_one_journal_title():
    journal = Journal(
        id=1,
        title="Example Journal",
        primary_issn="1234-5678",
        issns=("1234-5678",),
        publisher="",
        subscribed=True,
        last_checked_at=None,
        sort_rank=None,
    )
    other = Journal(
        id=2,
        title="Other Journal",
        primary_issn="9999-999X",
        issns=("9999-999X",),
        publisher="",
        subscribed=True,
        last_checked_at=None,
        sort_rank=None,
    )
    assert export_filename([journal]) == "example-journal-abstracts.md"
    assert export_filename([journal, other]) == "journal-abstracts.md"


def _paper(
    doi: str,
    title: str,
    *,
    abstract: str | None,
    volume: str,
    issue: str,
    published: str,
    authors: str = "Ada Lovelace",
) -> PaperHit:
    return PaperHit(
        doi=doi,
        title=title,
        authors=authors,
        abstract=abstract,
        published_date=published,
        url=f"https://doi.org/{doi}",
        volume=volume,
        issue=issue,
        issue_date=published[:7],
    )
