from datetime import date
from urllib.parse import unquote

import httpx
import pytest

from paper_cart.crossref import (
    CrossrefError,
    PaperHit,
    doi_from_query,
    fetch_papers,
    fetch_recent_issues,
    format_issued,
    is_non_article,
    issn_from_query,
    journal_for_doi,
    journal_for_issn,
    journal_search_url,
    looks_like_doi,
    looks_like_issn,
    normalize_doi,
    normalize_issn,
    parse_work,
    recent_works_url,
    search_journals,
    select_recent_issues,
    strip_jats,
    work_url,
    works_url,
)


def test_works_url_uses_created_date_and_skips_blank_mailto():
    url = works_url("0028-0836", date(2026, 9, 1), "created")
    decoded = unquote(url)
    assert "issn:0028-0836" in decoded
    assert "type:journal-article" in decoded
    assert "from-created-date:2026-09-01" in decoded
    assert "mailto" not in decoded
    assert "cursor=" in url


def test_works_url_uses_published_date_and_mailto():
    decoded = unquote(
        works_url("1476-4687", date(2026, 9, 16), "published", mailto="reader@example.com")
    )
    assert "from-pub-date:2026-09-16" in decoded
    assert "mailto=reader@example.com" in decoded


def test_journal_search_url_encodes_query():
    decoded = unquote(journal_search_url("political science"))
    assert decoded.startswith("https://api.crossref.org/journals?")
    assert "query=political science" in decoded or "query=political+science" in decoded
    assert "rows=20" in decoded


def test_strip_jats_and_non_article_titles():
    assert strip_jats("<jats:p>Hello&amp; welcome</jats:p>") == "Hello& welcome"
    assert strip_jats("   ") is None
    assert is_non_article("Editorial: a note")
    assert is_non_article("Table of contents")
    assert is_non_article("Erratum to: Something")
    assert not is_non_article("A model of editorial choice")


def test_normalize_issn_and_doi():
    assert normalize_issn("1234567x") == "1234-567X"
    assert normalize_issn("0028-0836") == "0028-0836"
    assert normalize_issn("not-an-issn") is None
    assert normalize_doi(" HTTPS://doi.org/10.1000/AbC ") == "10.1000/abc"


def test_parse_work_keeps_articles_and_drops_editorials():
    article = parse_work(
        {
            "DOI": "10.1000/AbC",
            "title": ["A real paper"],
            "author": [{"given": "Ada", "family": "Lovelace"}],
            "abstract": "<jats:p>Hello</jats:p>",
            "issued": {"date-parts": [[2026, 9, 1]]},
            "type": "journal-article",
        }
    )
    assert article is not None
    assert article.doi == "10.1000/abc"
    assert article.authors == "Ada Lovelace"
    assert article.abstract == "Hello"
    assert article.published_date == "2026-09-01"
    assert article.url == "https://doi.org/10.1000/abc"
    assert article.volume is None
    assert article.issue is None
    issued = parse_work(
        {
            "DOI": "10.1000/iss",
            "title": ["Issue paper"],
            "type": "journal-article",
            "volume": 12,
            "journal-issue": {
                "issue": "4",
                "published-print": {"date-parts": [[2026, 10]]},
            },
        }
    )
    assert issued is not None
    assert issued.volume == "12"
    assert issued.issue == "4"
    assert issued.issue_date == "2026-10"
    assert parse_work({"DOI": "10.1000/ed", "title": ["Editorial"], "type": "journal-article"}) is None
    assert format_issued({"date-parts": [[2026]]}) == "2026"


def test_recent_works_url_sorts_by_issued_date():
    decoded = unquote(recent_works_url("0028-0836", mailto="reader@example.com"))
    assert "issn:0028-0836" in decoded
    assert "type:journal-article" in decoded
    assert "sort=issued" in decoded
    assert "order=desc" in decoded
    assert "offset=0" in decoded
    assert "cursor=" not in decoded
    assert "from-created-date" not in decoded
    select = decoded.split("select=", 1)[1].split("&", 1)[0]
    fields = set(select.split(","))
    assert {"volume", "issue", "issued", "abstract"} <= fields
    assert "journal-issue" not in fields
    assert "mailto=reader@example.com" in decoded


def test_select_recent_issues_keeps_newest_and_drops_unassigned():
    papers = [
        _issue_hit("10.1000/four", "Newest", "12", "4", "2026-10-02", issue_date="2026-10"),
        _issue_hit("10.1000/four-b", "Also newest", "12", "4", "2026-10-01", issue_date="2026-10"),
        _issue_hit("10.1000/three", "Middle", "12", "3", "2026-09-01", issue_date="2026-09"),
        _issue_hit("10.1000/two", "Older", "12", "2", "2026-08-01", issue_date="2026-08"),
        _issue_hit("10.1000/online", "Online first", None, None, "2026-10-03"),
    ]
    groups = select_recent_issues(papers, 2)
    assert [(group.volume, group.issue) for group in groups] == [("12", "4"), ("12", "3")]
    assert [paper.doi for paper in groups[0].papers] == ["10.1000/four", "10.1000/four-b"]
    assert [paper.doi for paper in groups[1].papers] == ["10.1000/three"]
    assert select_recent_issues(papers, 0) == []


def test_fetch_recent_issues_stops_after_older_issues():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        decoded = unquote(str(request.url))
        assert "from-created-date" not in decoded
        assert "cursor" not in request.url.params
        assert "journal-issue" not in decoded
        assert request.url.params.get("sort") == "issued"
        assert request.url.params.get("order") == "desc"
        rows = int(request.url.params.get("rows") or "0")
        offset = int(request.url.params.get("offset") or "0")
        if offset == 0:
            items = [
                _work("10.1000/a", "Newest", volume="12", issue="4", issued=[2026, 10, 2]),
                _work("10.1000/b", "Also newest", volume="12", issue="4", issued=[2026, 10, 1]),
            ]
        elif offset == rows:
            items = [
                _work("10.1000/c", "Middle", volume="12", issue="3", issued=[2026, 9, 1]),
                _work("10.1000/online", "Online first", issued=[2026, 8, 15]),
            ]
        elif offset == rows * 2:
            items = [
                _work("10.1000/d", "Older issue", volume="12", issue="2", issued=[2026, 8, 1]),
            ]
        else:
            raise AssertionError("fetched past the requested issues")
        return _json({"message": {"items": items, "total-results": 500}})

    groups = fetch_recent_issues(
        ("0028-0836",),
        2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        pause=lambda: None,
    )
    assert [(group.volume, group.issue) for group in groups] == [("12", "4"), ("12", "3")]
    dois = [paper.doi for group in groups for paper in group.papers]
    assert dois == ["10.1000/a", "10.1000/b", "10.1000/c"]
    assert calls["n"] == 3


def test_fetch_recent_issues_stops_when_the_result_list_ends():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.params.get("offset") == "0"
        return _json(
            {
                "message": {
                    "items": [_work("10.1000/only", "Only paper", volume="1", issue="1")],
                    "total-results": 1,
                }
            }
        )

    groups = fetch_recent_issues(
        ("1234-5678",),
        4,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        pause=lambda: None,
    )
    assert calls["n"] == 1
    assert [(group.volume, group.issue) for group in groups] == [("1", "1")]
    assert [paper.doi for paper in groups[0].papers] == ["10.1000/only"]


def test_fetch_unions_created_and_published_and_drops_non_articles():
    def handler(request: httpx.Request) -> httpx.Response:
        decoded = unquote(str(request.url))
        assert request.headers["user-agent"] == "PaperCart/0.1"
        cursor = request.url.params.get("cursor")
        if "from-created-date" in decoded and cursor == "*":
            return _json(
                {
                    "message": {
                        "items": [
                            _work("10.1000/new", "A real paper"),
                            _work("10.1000/ed", "Editorial: note"),
                        ],
                        "next-cursor": "page-2",
                    }
                }
            )
        if cursor == "page-2":
            return _json({"message": {"items": []}})
        if "from-pub-date" in decoded:
            return _json(
                {
                    "message": {
                        "items": [
                            _work("10.1000/new", "A real paper"),
                            _work("10.1000/pub-only", "Published later"),
                        ],
                        "next-cursor": "done",
                    }
                }
            )
        return _json({"message": {"items": []}})

    papers = fetch_papers(
        ("0028-0836",),
        date(2026, 9, 1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        pause=lambda: None,
    )
    assert [paper.doi for paper in papers] == ["10.1000/new", "10.1000/pub-only"]
    assert papers[0].abstract == "Hello"


def test_fetch_retries_when_crossref_is_busy():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        decoded = unquote(str(request.url))
        if "from-created-date" in decoded and calls["n"] == 2:
            return _json(
                {
                    "message": {
                        "items": [_work("10.1000/retry", "After retry")],
                        "next-cursor": "end",
                    }
                }
            )
        return _json({"message": {"items": []}})

    papers = fetch_papers(
        ("0028-0836",),
        date(2026, 9, 1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        pause=lambda: None,
    )
    assert [paper.doi for paper in papers] == ["10.1000/retry"]


def test_search_journals_parses_issns():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/journals" in str(request.url)
        assert "rows=20" in str(request.url)
        return _json(
            {
                "message": {
                    "items": [
                        {
                            "title": "Example Journal",
                            "publisher": "Example Press",
                            "ISSN": ["12345678", "8765-432X"],
                        },
                        {"title": "No ISSN"},
                    ]
                }
            }
        )

    hits = search_journals(
        "example",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert len(hits) == 1
    assert hits[0].title == "Example Journal"
    assert hits[0].issns == ("1234-5678", "8765-432X")
    assert hits[0].publisher == "Example Press"


def test_doi_and_issn_queries_stay_on_their_own_paths():
    assert looks_like_doi("10.1111/ajps.12700")
    assert looks_like_doi("  HTTPS://doi.org/10.1111/ajps.12700 ")
    assert looks_like_doi("http://dx.doi.org/10.1111/AJPS.12700")
    assert doi_from_query("https://doi.org/10.1111%2Fajps.12700") == "10.1111/ajps.12700"
    assert not looks_like_doi("Nature")
    assert not looks_like_doi("0092-5853")
    assert looks_like_issn("0092-5853")
    assert looks_like_issn("00925853")
    assert looks_like_issn("ISSN 1540-5907")
    assert looks_like_issn("issn:0092-5853")
    assert looks_like_issn("0092 5853")
    assert issn_from_query("00925853") == "0092-5853"
    assert issn_from_query("0000-006X") == "0000-006X"
    assert looks_like_issn("1234-5678")
    assert issn_from_query("1234-5678") is None
    assert not looks_like_issn("Nature")
    assert not looks_like_issn("PLOS ONE")
    assert not looks_like_issn("10.1111/ajps.12700")
    assert not looks_like_issn("978-0-306-40615-7")
    assert not looks_like_doi("978-0-306-40615-7")
    assert work_url("10.1111/ajps.12700") == "https://api.crossref.org/works/10.1111%2Fajps.12700"


def test_journal_for_doi_returns_the_container_journal():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/works/" in request.url.path
        assert "10.1111/ajps.12700" in unquote(str(request.url))
        assert "mailto=reader@example.com" in unquote(str(request.url))
        return _json(
            {
                "message": {
                    "DOI": "10.1111/ajps.12700",
                    "type": "journal-article",
                    "title": ["Editorial"],
                    "container-title": ["American Journal of Political Science"],
                    "ISSN": ["0092-5853", "1540-5907"],
                    "publisher": "Wiley",
                }
            }
        )

    hit = journal_for_doi(
        "https://doi.org/10.1111/AJPS.12700",
        mailto="reader@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert hit.title == "American Journal of Political Science"
    assert hit.issns == ("0092-5853", "1540-5907")
    assert hit.publisher == "Wiley"


def test_journal_for_doi_rejects_a_work_without_a_journal():
    def respond(message: dict) -> httpx.Response:
        return _json({"message": message})

    book = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: respond(
                {
                    "type": "book",
                    "container-title": ["A Book"],
                    "ISSN": ["0092-5853"],
                    "publisher": "Press",
                }
            )
        )
    )
    with pytest.raises(CrossrefError, match="not a journal article"):
        journal_for_doi("10.1000/book", client=book)

    loose = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: respond(
                {
                    "type": "journal-article",
                    "title": ["A paper"],
                    "publisher": "Press",
                }
            )
        )
    )
    with pytest.raises(CrossrefError, match="no container journal"):
        journal_for_doi("10.1000/loose", client=loose)


def test_journal_for_issn_reads_the_journal_record():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/journals/0092-5853")
        assert "query=" not in str(request.url)
        assert "mailto=reader@example.com" in unquote(str(request.url))
        return _json(
            {
                "message": {
                    "title": "American Journal of Political Science",
                    "publisher": "Wiley",
                    "ISSN": ["0092-5853", "1540-5907"],
                }
            }
        )

    hit = journal_for_issn(
        "ISSN 0092 5853",
        mailto="reader@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert hit.title == "American Journal of Political Science"
    assert hit.issns == ("0092-5853", "1540-5907")
    assert hit.publisher == "Wiley"


def test_journal_for_issn_explains_a_miss_and_a_bad_checksum():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/journals/0000-0000"):
            return httpx.Response(404)
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(CrossrefError, match="no journal for that ISSN"):
        journal_for_issn("0000-0000", client=client)
    with pytest.raises(CrossrefError, match="returned 503"):
        journal_for_issn("0092-5853", client=client)
    with pytest.raises(CrossrefError, match="not valid"):
        journal_for_issn("1234-5678", client=client)


def _work(
    doi: str,
    title: str,
    *,
    volume: str | None = None,
    issue: str | None = None,
    issued: list[int] | None = None,
) -> dict:
    item = {
        "DOI": doi,
        "title": [title],
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "abstract": "<jats:p>Hello</jats:p>",
        "issued": {"date-parts": [issued or [2026, 9, 1]]},
        "type": "journal-article",
    }
    if volume is not None:
        item["volume"] = volume
    if issue is not None:
        item["issue"] = issue
        item["journal-issue"] = {
            "issue": issue,
            "published-print": {"date-parts": [issued or [2026, 9, 1]]},
        }
    return item


def _issue_hit(
    doi: str,
    title: str,
    volume: str | None,
    issue: str | None,
    published: str,
    *,
    issue_date: str | None = None,
) -> PaperHit:
    return PaperHit(
        doi=doi,
        title=title,
        authors="Ada Lovelace",
        abstract="Hello",
        published_date=published,
        url=f"https://doi.org/{doi}",
        volume=volume,
        issue=issue,
        issue_date=issue_date,
    )


def _json(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)
