"""Crossref journal search, DOI and ISSN lookup, and new-article fetches."""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable
from urllib.parse import quote, unquote, urlencode

import httpx

API = "https://api.crossref.org"
USER_AGENT = "PaperCart/0.1"
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_DOI_PREFIX = re.compile(r"(?i)^https?://(dx\.)?doi\.org/")
_DOI_LABEL = re.compile(r"(?i)^doi:\s*")
_BARE_DOI = re.compile(r"(?i)^10\.\d{4,9}/\S+$")
_ISSN_LABEL = re.compile(r"(?i)^issn[\s:]+")
NOT_A_JOURNAL_ARTICLE = "That DOI is not a journal article."
NO_CONTAINER_JOURNAL = "Crossref has no container journal for that DOI."
ISSN_NOT_VALID = "That ISSN is not valid."
NO_JOURNAL_FOR_ISSN = "Crossref has no journal for that ISSN."


class CrossrefError(Exception):
    """A Crossref request failed without including the request URL."""


@dataclass(frozen=True)
class JournalHit:
    title: str
    issns: tuple[str, ...]
    publisher: str


@dataclass(frozen=True)
class PaperHit:
    doi: str
    title: str
    authors: str
    abstract: str | None
    published_date: str | None
    url: str
    volume: str | None = None
    issue: str | None = None
    issue_date: str | None = None


@dataclass(frozen=True)
class IssueGroup:
    volume: str | None
    issue: str | None
    date: str | None
    papers: tuple[PaperHit, ...]

    @property
    def label(self) -> str:
        parts: list[str] = []
        if self.volume:
            parts.append(f"Volume {self.volume}")
        if self.issue:
            parts.append(f"Issue {self.issue}")
        return ", ".join(parts) or "Issue"

    @property
    def key(self) -> tuple[str, str]:
        return (self.volume or "", self.issue or "")


def user_agent(mailto: str | None) -> str:
    if mailto:
        return f"{USER_AGENT} (mailto:{mailto})"
    return USER_AGENT


def normalize_issn(value: str) -> str | None:
    raw = value.strip().upper().replace("-", "")
    if not re.fullmatch(r"\d{7}[\dX]", raw):
        return None
    return f"{raw[:4]}-{raw[4:]}"


def normalize_issns(values: Iterable[str]) -> tuple[str, ...]:
    found: list[str] = []
    for value in values:
        issn = normalize_issn(value)
        if issn and issn not in found:
            found.append(issn)
    return tuple(found)


def normalize_doi(value: str) -> str:
    doi = _DOI_PREFIX.sub("", value.strip())
    return doi.lower()


def looks_like_doi(value: str) -> bool:
    """A bare DOI, a doi: label, or a doi.org URL. Journal names stay name search."""
    text = value.strip()
    if not text:
        return False
    if _DOI_LABEL.match(text) or _DOI_PREFIX.match(text):
        return True
    return _BARE_DOI.fullmatch(text) is not None


def doi_from_query(value: str) -> str | None:
    text = value.strip()
    text = _DOI_LABEL.sub("", text)
    text = _DOI_PREFIX.sub("", text)
    text = unquote(text).strip().rstrip("/")
    if _BARE_DOI.fullmatch(text):
        return text.lower()
    return None


def work_url(doi: str, *, mailto: str | None = None) -> str:
    url = f"{API}/works/{quote(doi, safe='')}"
    if mailto:
        return f"{url}?{urlencode({'mailto': mailto})}"
    return url


def _issn_query_body(value: str) -> str:
    text = _ISSN_LABEL.sub("", value.strip(), count=1).strip()
    compact = re.sub(r"\s+", "", text)
    if normalize_issn(compact):
        return compact
    return text


def looks_like_issn(value: str) -> bool:
    """An ISSN, with or without the hyphen or an ISSN label. Names stay name search."""
    return normalize_issn(_issn_query_body(value)) is not None


def issn_checksum_ok(value: str) -> bool:
    raw = value.strip().upper().replace("-", "")
    if not re.fullmatch(r"\d{7}[\dX]", raw):
        return False
    total = sum(int(raw[index]) * (8 - index) for index in range(7))
    remainder = total % 11
    expected = 0 if remainder == 0 else 11 - remainder
    check = raw[7]
    if expected == 10:
        return check == "X"
    return check == str(expected)


def issn_from_query(value: str) -> str | None:
    issn = normalize_issn(_issn_query_body(value))
    if issn is None or not issn_checksum_ok(issn):
        return None
    return issn


def journal_issn_url(issn: str, *, mailto: str | None = None) -> str:
    url = f"{API}/journals/{quote(issn, safe='')}"
    if mailto:
        return f"{url}?{urlencode({'mailto': mailto})}"
    return url


def strip_jats(value: str | None) -> str | None:
    if not value:
        return None
    text = _TAG.sub(" ", value)
    text = html.unescape(text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text or None


def journal_search_url(query: str, *, rows: int = 20, mailto: str | None = None) -> str:
    params = {"query": query, "rows": str(rows)}
    if mailto:
        params["mailto"] = mailto
    return f"{API}/journals?{urlencode(params)}"


def works_url(
    issn: str,
    start: date,
    field: str,
    *,
    rows: int = 100,
    cursor: str = "*",
    mailto: str | None = None,
) -> str:
    date_filter = "from-created-date" if field == "created" else "from-pub-date"
    params = {
        "filter": f"issn:{issn},type:journal-article,{date_filter}:{start.isoformat()}",
        "rows": str(rows),
        "cursor": cursor,
        "select": "DOI,title,author,abstract,URL,issued,container-title,type",
    }
    if mailto:
        params["mailto"] = mailto
    return f"{API}/works?{urlencode(params)}"


def recent_works_url(
    issn: str,
    *,
    rows: int = 100,
    offset: int = 0,
    mailto: str | None = None,
) -> str:
    """Newest articles first.

    Crossref rejects cursor paging when results are sorted by issue date, and
    it has no journal-issue select. Offset paging can be sorted, and volume
    and issue are enough to group a recent issue.
    """
    params = {
        "filter": f"issn:{issn},type:journal-article",
        "rows": str(rows),
        "offset": str(offset),
        "sort": "issued",
        "order": "desc",
        "select": "DOI,title,author,abstract,URL,issued,volume,issue,container-title,type",
    }
    if mailto:
        params["mailto"] = mailto
    return f"{API}/works?{urlencode(params)}"


def search_journals(
    query: str,
    *,
    mailto: str | None = None,
    client: httpx.Client | None = None,
) -> list[JournalHit]:
    owns_client = client is None
    client = client or _client(mailto)
    try:
        payload = _get_json(client, journal_search_url(query, mailto=mailto), mailto)
    finally:
        if owns_client:
            client.close()
    items = (payload.get("message") or {}).get("items") or []
    hits: list[JournalHit] = []
    for item in items:
        hit = parse_journal(item)
        if hit is not None:
            hits.append(hit)
    return hits


def journal_for_doi(
    query: str,
    *,
    mailto: str | None = None,
    client: httpx.Client | None = None,
) -> JournalHit:
    """Return the journal that contains this article."""
    doi = doi_from_query(query)
    if doi is None:
        raise CrossrefError(NOT_A_JOURNAL_ARTICLE)
    owns_client = client is None
    client = client or _client(mailto)
    try:
        payload = _get_json(client, work_url(doi, mailto=mailto), mailto)
    finally:
        if owns_client:
            client.close()
    message = payload.get("message")
    if not isinstance(message, dict):
        raise CrossrefError("Crossref returned an unreadable response.")
    if message.get("type") != "journal-article":
        raise CrossrefError(NOT_A_JOURNAL_ARTICLE)
    hit = _container_journal(message)
    if hit is None:
        raise CrossrefError(NO_CONTAINER_JOURNAL)
    return hit


def journal_for_issn(
    query: str,
    *,
    mailto: str | None = None,
    client: httpx.Client | None = None,
) -> JournalHit:
    """Return the journal this ISSN identifies."""
    issn = issn_from_query(query)
    if issn is None:
        raise CrossrefError(ISSN_NOT_VALID)
    owns_client = client is None
    client = client or _client(mailto)
    try:
        try:
            payload = _get_json(client, journal_issn_url(issn, mailto=mailto), mailto)
        except CrossrefError as exc:
            if str(exc) == "Crossref returned 404.":
                raise CrossrefError(NO_JOURNAL_FOR_ISSN) from exc
            raise
    finally:
        if owns_client:
            client.close()
    message = payload.get("message")
    if not isinstance(message, dict):
        raise CrossrefError("Crossref returned an unreadable response.")
    hit = parse_journal(message)
    if hit is None:
        raise CrossrefError(NO_JOURNAL_FOR_ISSN)
    return hit


def fetch_papers(
    issns: tuple[str, ...] | list[str],
    start: date,
    *,
    mailto: str | None = None,
    client: httpx.Client | None = None,
    pause: Callable[[], None] | None = None,
) -> list[PaperHit]:
    if pause is None:
        delay = 0.05 if mailto else 1.0

        def pause() -> None:
            time.sleep(delay)

    owns_client = client is None
    client = client or _client(mailto)
    by_doi: dict[str, PaperHit] = {}
    try:
        for issn in issns:
            for field in ("created", "published"):
                for item in _collect_works(client, issn, start, field, mailto, pause):
                    paper = parse_work(item)
                    if paper is not None and paper.doi not in by_doi:
                        by_doi[paper.doi] = paper
    finally:
        if owns_client:
            client.close()
    return list(by_doi.values())


def fetch_recent_issues(
    issns: tuple[str, ...] | list[str],
    issue_count: int,
    *,
    mailto: str | None = None,
    client: httpx.Client | None = None,
    pause: Callable[[], None] | None = None,
    progress: Callable[[float], None] | None = None,
) -> list[IssueGroup]:
    """Return papers in the most recent `issue_count` issues, newest issue first.

    `progress`, if given, is called with a rough share of the work done (0 to 1)
    after each page from Crossref.
    """
    if issue_count < 1:
        return []
    if pause is None:
        delay = 0.05 if mailto else 1.0

        def pause() -> None:
            time.sleep(delay)

    owns_client = client is None
    client = client or _client(mailto)
    by_doi: dict[str, PaperHit] = {}
    try:
        for index, issn in enumerate(issns):

            def report(share: float, index: int = index) -> None:
                if progress is not None:
                    progress((index + share) / len(issns))

            for item in _collect_recent_works(
                client, issn, issue_count, mailto, pause, report
            ):
                paper = parse_work(item)
                if paper is not None and paper.doi not in by_doi:
                    by_doi[paper.doi] = paper
            report(1.0)
    finally:
        if owns_client:
            client.close()
    return select_recent_issues(list(by_doi.values()), issue_count)


def select_recent_issues(papers: Iterable[PaperHit], issue_count: int) -> list[IssueGroup]:
    if issue_count < 1:
        return []
    grouped: dict[tuple[str, str], list[PaperHit]] = {}
    for paper in papers:
        key = issue_key(paper)
        if key is None:
            continue
        grouped.setdefault(key, []).append(paper)
    ranked = sorted(
        grouped,
        key=lambda key: (_group_date(grouped[key]), key[0], key[1]),
        reverse=True,
    )
    selected: list[IssueGroup] = []
    for key in ranked[:issue_count]:
        items = _sorted_issue_papers(grouped[key])
        date = _group_date(items) or None
        selected.append(
            IssueGroup(
                volume=key[0] or None,
                issue=key[1] or None,
                date=date,
                papers=tuple(items),
            )
        )
    return selected


def issue_key(paper: PaperHit) -> tuple[str, str] | None:
    volume = (paper.volume or "").strip()
    issue = (paper.issue or "").strip()
    if not volume and not issue:
        return None
    return (volume, issue)


def parse_journal(item: dict) -> JournalHit | None:
    title = _first_text(item.get("title"))
    issns = normalize_issns(item.get("ISSN") or [])
    if not title or not issns:
        return None
    publisher = _first_text(item.get("publisher"))
    return JournalHit(title=title, issns=issns, publisher=publisher)


def _container_journal(item: dict) -> JournalHit | None:
    title = _first_text(item.get("container-title"))
    issns = normalize_issns(item.get("ISSN") or [])
    if not title or not issns:
        return None
    return JournalHit(title=title, issns=issns, publisher=_first_text(item.get("publisher")))


def parse_work(item: dict) -> PaperHit | None:
    """One Crossref journal article, or None.

    Titles are never used to skip a work: editorials, corrections and other
    notices are kept, so a real paper is never lost to a title that happens to
    look like a notice. Only works Crossref does not call journal articles
    (figures, datasets, peer reviews) are left out.
    """
    work_type = item.get("type")
    if work_type and work_type != "journal-article":
        return None
    title = _first_text(item.get("title"))
    doi = normalize_doi(str(item.get("DOI") or ""))
    if not title or not doi:
        return None
    volume, issue, issue_date = _issue_fields(item)
    return PaperHit(
        doi=doi,
        title=title,
        authors=format_authors(item.get("author")),
        abstract=strip_jats(item.get("abstract")),
        published_date=format_issued(item.get("issued")),
        url=f"https://doi.org/{doi}",
        volume=volume,
        issue=issue,
        issue_date=issue_date,
    )


def format_authors(authors: object) -> str:
    if not isinstance(authors, list):
        return ""
    names: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        literal = str(author.get("name") or "").strip()
        if literal:
            names.append(literal)
            continue
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or "").strip()
        name = f"{given} {family}".strip()
        if name:
            names.append(name)
    return ", ".join(names)


def format_issued(issued: object) -> str | None:
    if not isinstance(issued, dict):
        return None
    parts = issued.get("date-parts") or []
    if not parts or not isinstance(parts[0], list) or not parts[0]:
        return None
    numbers = parts[0]
    try:
        year = int(numbers[0])
    except (TypeError, ValueError):
        return None
    if len(numbers) == 1:
        return f"{year:04d}"
    try:
        month = int(numbers[1])
    except (TypeError, ValueError):
        return f"{year:04d}"
    if len(numbers) == 2:
        return f"{year:04d}-{month:02d}"
    try:
        day = int(numbers[2])
    except (TypeError, ValueError):
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _collect_recent_works(
    client: httpx.Client,
    issn: str,
    issue_count: int,
    mailto: str | None,
    pause: Callable[[], None],
    progress: Callable[[float], None] | None = None,
) -> list[dict]:
    offset = 0
    rows = 100
    seen_offsets: set[int] = set()
    found: list[dict] = []
    parsed: list[PaperHit] = []
    while offset not in seen_offsets and offset < 10_000 and len(found) < 2000:
        seen_offsets.add(offset)
        payload = _get_json(
            client,
            recent_works_url(issn, rows=rows, offset=offset, mailto=mailto),
            mailto,
        )
        pause()
        message = payload.get("message") or {}
        items = [item for item in (message.get("items") or []) if isinstance(item, dict)]
        if not items:
            break
        found.extend(items)
        page_keys: set[tuple[str, str]] = set()
        for item in items:
            paper = parse_work(item)
            if paper is None:
                continue
            parsed.append(paper)
            key = issue_key(paper)
            if key is not None:
                page_keys.add(key)
        groups = select_recent_issues(parsed, issue_count)
        distinct = {key for paper in parsed if (key := issue_key(paper))}
        if progress is not None:
            # Hold back the last tenth: one more page may be needed to confirm the cutoff.
            progress(0.9 * min(len(distinct), issue_count) / issue_count)
        if (
            len(distinct) > issue_count
            and page_keys
            and page_keys.isdisjoint(group.key for group in groups)
        ):
            break
        total = message.get("total-results")
        if isinstance(total, int) and not isinstance(total, bool):
            if offset + len(items) >= total:
                break
        elif len(items) < rows:
            break
        offset += rows
    return found


def _issue_fields(item: dict) -> tuple[str | None, str | None, str | None]:
    volume = _token(item.get("volume")) or None
    issue = _token(item.get("issue")) or None
    issue_date = None
    journal_issue = item.get("journal-issue")
    if isinstance(journal_issue, dict):
        if not issue:
            issue = _token(journal_issue.get("issue")) or None
        issue_date = format_issued(journal_issue.get("published-print")) or format_issued(
            journal_issue.get("published-online")
        )
    return volume, issue, issue_date


def _token(value: object) -> str:
    if isinstance(value, list):
        return _token(value[0]) if value else ""
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _group_date(papers: list[PaperHit]) -> str:
    dates = [paper.issue_date or paper.published_date or "" for paper in papers]
    return max(dates) if dates else ""


def _sorted_issue_papers(papers: list[PaperHit]) -> list[PaperHit]:
    dated = [paper for paper in papers if paper.published_date]
    undated = [paper for paper in papers if not paper.published_date]
    dated.sort(key=lambda paper: paper.title.casefold())
    dated.sort(key=lambda paper: paper.published_date or "", reverse=True)
    undated.sort(key=lambda paper: paper.title.casefold())
    return dated + undated


def _collect_works(
    client: httpx.Client,
    issn: str,
    start: date,
    field: str,
    mailto: str | None,
    pause: Callable[[], None],
) -> list[dict]:
    cursor = "*"
    seen_cursors: set[str] = set()
    found: list[dict] = []
    while cursor not in seen_cursors and len(found) < 2000:
        seen_cursors.add(cursor)
        payload = _get_json(
            client,
            works_url(issn, start, field, cursor=cursor, mailto=mailto),
            mailto,
        )
        pause()
        message = payload.get("message") or {}
        items = message.get("items") or []
        if not items:
            break
        found.extend(item for item in items if isinstance(item, dict))
        next_cursor = message.get("next-cursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = str(next_cursor)
    return found


def _get_json(client: httpx.Client, url: str, mailto: str | None) -> dict:
    headers = {"User-Agent": user_agent(mailto), "Accept": "application/json"}
    delay = 1.0
    for attempt in range(4):
        try:
            response = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise CrossrefError("Crossref could not be reached.") from exc
        if response.status_code == 429 and attempt < 3:
            time.sleep(_retry_after(response, delay))
            delay *= 2
            continue
        if response.status_code == 429:
            raise CrossrefError("Crossref asked us to slow down. Try again in a moment.")
        if response.status_code >= 400:
            raise CrossrefError(f"Crossref returned {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CrossrefError("Crossref returned an unreadable response.") from exc
        if not isinstance(payload, dict):
            raise CrossrefError("Crossref returned an unreadable response.")
        return payload
    raise CrossrefError("Crossref asked us to slow down. Try again in a moment.")


def _retry_after(response: httpx.Response, fallback: float) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        wait = float(raw)
    except ValueError:
        wait = fallback
    return min(max(wait, 0.0), 10.0)


def _client(mailto: str | None) -> httpx.Client:
    return httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": user_agent(mailto), "Accept": "application/json"},
    )


def _first_text(value: object) -> str:
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    if isinstance(value, str):
        return value.strip()
    return ""
