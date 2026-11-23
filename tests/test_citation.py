import json

import httpx
import pytest

from paper_cart.citation import cite, split_name
from paper_cart.crossref import PaperHit, citations_url, fetch_citations, parse_work
from paper_cart.db import Paper, init_db, list_papers, subscribe_journal, upsert_papers
from paper_cart.refresh import backfill_citations


def _paper(**fields) -> Paper:
    citation = fields.pop("citation", None)
    values = {
        "doi": "10.1000/xyz.42",
        "journal_title": "Journal of Politics",
        "title": "Coalition Bargaining under Divided Executives",
        "authors": "",
        "abstract": None,
        "published_date": "2026-10-14",
        "url": "https://doi.org/10.1000/xyz.42",
        "status": "new",
        "citation_data": json.dumps(citation) if citation is not None else None,
    }
    values.update(fields)
    return Paper(**values)


THREE = {
    "authors": [
        {"given": "Sun-Woo", "family": "Kwak"},
        {"given": "Maria", "family": "van der Berg"},
        {"given": "Daniel J.", "family": "Okafor", "suffix": "Jr."},
    ],
    "volume": "58",
    "issue": "4",
    "page": "611-639",
}


def test_apa_journal_article():
    citation = cite(_paper(citation=THREE), "apa")
    assert citation.text == (
        "Kwak, S.-W., van der Berg, M., & Okafor, D. J., Jr. (2026). "
        "Coalition Bargaining under Divided Executives. Journal of Politics, 58(4), 611–639. "
        "https://doi.org/10.1000/xyz.42"
    )
    assert "<i>Journal of Politics</i>, <i>58</i>(4)" in citation.html
    assert "&amp;" in citation.html


def test_chicago_author_date_journal_article():
    citation = cite(_paper(citation=THREE), "chicago")
    assert citation.text == (
        "Kwak, Sun-Woo, Maria van der Berg, and Daniel J. Okafor Jr. 2026. "
        "“Coalition Bargaining under Divided Executives.” Journal of Politics 58 (4): 611–39. "
        "https://doi.org/10.1000/xyz.42."
    )
    assert "<i>Journal of Politics</i> 58 (4)" in citation.html


def test_unknown_style_falls_back_to_apa():
    assert cite(_paper(citation=THREE), "mla") == cite(_paper(citation=THREE), "apa")


def test_one_and_two_authors_and_group_authors():
    one = {"authors": [{"given": "Lena", "family": "Hoffmann"}]}
    two = {"authors": [{"given": "Lena", "family": "Hoffmann"}, {"name": "Pew Research Center"}]}
    assert cite(_paper(citation=one), "apa").text.startswith("Hoffmann, L. (2026). ")
    assert cite(_paper(citation=one), "chicago").text.startswith("Hoffmann, Lena. 2026. ")
    assert cite(_paper(citation=two), "apa").text.startswith(
        "Hoffmann, L., & Pew Research Center. (2026). "
    )
    assert cite(_paper(citation=two), "chicago").text.startswith(
        "Hoffmann, Lena, and Pew Research Center. 2026. "
    )


def test_long_author_lists_are_cut_as_each_style_says():
    many = {"authors": [{"given": f"Ann {chr(65 + n)}", "family": f"Author{n}"} for n in range(22)]}
    apa = cite(_paper(citation=many), "apa").text
    assert "Author18, A. S., . . . Author21, A. V. (2026)." in apa
    assert "Author19" not in apa
    chicago = cite(_paper(citation=many), "chicago").text
    assert chicago.startswith("Author0, Ann A, Ann B Author1, ")
    assert "Ann G Author6, et al. 2026." in chicago
    assert "Author7" not in chicago


def test_missing_parts_are_left_out_cleanly():
    bare = _paper(citation={"authors": [{"given": "Lena", "family": "Hoffmann"}]}, published_date=None)
    assert cite(bare, "apa").text == (
        "Hoffmann, L. (n.d.). Coalition Bargaining under Divided Executives. Journal of Politics. "
        "https://doi.org/10.1000/xyz.42"
    )
    assert cite(bare, "chicago").text == (
        "Hoffmann, Lena. n.d. “Coalition Bargaining under Divided Executives.” Journal of Politics. "
        "https://doi.org/10.1000/xyz.42."
    )
    article = _paper(citation={"authors": [], "volume": "12", "article_number": "104117"})
    assert cite(article, "apa").text == (
        "Coalition Bargaining under Divided Executives. (2026). Journal of Politics, 12, Article 104117. "
        "https://doi.org/10.1000/xyz.42"
    )
    assert "Journal of Politics 12: 104117. " in cite(article, "chicago").text


def test_titles_ending_in_a_question_and_subtitles():
    paper = _paper(
        title="Who Pays for Decentralization?",
        citation={"authors": [{"given": "Lena", "family": "Hoffmann"}], "subtitle": "Transfers and Blame"},
    )
    assert "(2026). Who Pays for Decentralization? Transfers and Blame. Journal" in cite(paper, "apa").text
    assert "“Who Pays for Decentralization? Transfers and Blame.” Journal" in cite(paper, "chicago").text
    plain = _paper(title="Why Vote?", citation={"authors": []})
    assert "Why Vote? (2026)." in cite(plain, "apa").text
    assert "“Why Vote?” 2026." in cite(plain, "chicago").text


def test_papers_without_lookup_use_the_saved_names():
    paper = _paper(authors="Grace Liu, Tomás de la Fuente, Ludwig van Beethoven")
    assert cite(paper, "apa").text.startswith("Liu, G., de la Fuente, T., & van Beethoven, L. (2026). ")
    assert split_name("Plato").family == "Plato"
    # A lookup that found nothing still falls back to the saved names.
    known = _paper(authors="Grace Liu", citation={})
    assert cite(known, "chicago").text.startswith("Liu, Grace. 2026. ")


@pytest.mark.parametrize(
    ("pages", "short"),
    [
        ("3-10", "3–10"),
        ("96-117", "96–117"),
        ("100-104", "100–104"),
        ("101-108", "101–8"),
        ("808-833", "808–33"),
        ("321-328", "321–28"),
        ("498-532", "498–532"),
        ("1087-1089", "1087–89"),
        ("2787-2816", "2787–2816"),
        ("e12-e20", "e12–e20"),
    ],
)
def test_chicago_shortens_page_ranges(pages, short):
    paper = _paper(citation={"authors": [], "volume": "1", "page": pages})
    assert f"Journal of Politics 1: {short}. " in cite(paper, "chicago").text
    assert f"Journal of Politics, 1, {pages.replace('-', '–')}. " in cite(paper, "apa").text


def test_parse_work_keeps_citation_fields():
    hit = parse_work(
        {
            "DOI": "10.1000/XYZ.42",
            "title": ["A Title"],
            "subtitle": ["The <i>Subtitle</i>"],
            "author": [
                {"given": "Sun-Woo", "family": "Kwak", "sequence": "first"},
                {"name": "Pew Research Center"},
                {"given": "", "family": ""},
            ],
            "volume": "58",
            "issue": "4",
            "page": "611-639",
            "type": "journal-article",
        }
    )
    assert hit.citation == {
        "authors": [{"given": "Sun-Woo", "family": "Kwak"}, {"name": "Pew Research Center"}],
        "subtitle": "The Subtitle",
        "volume": "58",
        "issue": "4",
        "page": "611-639",
    }


def test_fetch_citations_asks_for_dois_in_batches():
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.params["filter"])
        items = [
            {"DOI": doi.removeprefix("doi:").upper(), "author": [{"given": "A", "family": "B"}], "volume": "1"}
            for doi in request.url.params["filter"].split(",")
            if not doi.endswith("missing")
        ]
        return httpx.Response(200, json={"message": {"items": items}})

    dois = [f"10.1000/{n}" for n in range(45)] + ["10.1000/missing"]
    found = fetch_citations(
        dois, client=httpx.Client(transport=httpx.MockTransport(handler)), pause=lambda: None
    )
    assert len(asked) == 2
    assert len(found) == 45
    assert found["10.1000/7"] == {"authors": [{"given": "A", "family": "B"}], "volume": "1"}
    assert "select=DOI%2Cauthor%2Csubtitle" in citations_url(["10.1/a"])


def test_update_stores_citation_fields_and_backfill_fills_older_papers(tmp_path):
    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    journal = subscribe_journal(db_path, title="Journal of Politics", issns=("1234-5678",), publisher="")
    old = PaperHit(
        doi="10.1000/old",
        title="Old",
        authors="Grace Liu",
        abstract=None,
        published_date="2025",
        url="https://doi.org/10.1000/old",
    )
    gone = PaperHit(**{**old.__dict__, "doi": "10.1000/gone", "url": "https://doi.org/10.1000/gone"})
    new = PaperHit(**{**old.__dict__, "doi": "10.1000/new", "citation": {"authors": [], "volume": "3"}})
    upsert_papers(db_path, journal, "Journal of Politics", [old, gone, new])
    stored = {paper.doi: paper.citation_data for paper in list_papers(db_path, "all")}
    assert stored == {"10.1000/old": None, "10.1000/gone": None, "10.1000/new": '{"authors": [], "volume": "3"}'}

    asked: list[list[str]] = []

    def fetch(dois, *, mailto=None, client=None):
        asked.append(sorted(dois))
        return {"10.1000/old": {"authors": [{"given": "Grace", "family": "Liu"}], "volume": "9"}}

    assert backfill_citations(db_path, fetch=fetch, mailto=None) == 2
    assert asked == [["10.1000/gone", "10.1000/old"]]
    stored = {paper.doi: paper.citation_data for paper in list_papers(db_path, "all")}
    assert json.loads(stored["10.1000/old"])["volume"] == "9"
    # Crossref did not know this one, so it is not asked about again.
    assert stored["10.1000/gone"] == "{}"
    assert backfill_citations(db_path, fetch=fetch, mailto=None) == 0

    # A later update without citation fields keeps what was stored.
    upsert_papers(db_path, journal, "Journal of Politics", [old])
    assert json.loads(list_papers(db_path, "all", query="old")[0].citation_data)["volume"] == "9"


def test_backfill_stops_quietly_when_crossref_fails(tmp_path):
    from paper_cart.crossref import CrossrefError

    db_path = tmp_path / "library.sqlite"
    init_db(db_path)
    journal = subscribe_journal(db_path, title="J", issns=("1234-5678",), publisher="")
    upsert_papers(
        db_path,
        journal,
        "J",
        [PaperHit(doi="10.1/a", title="A", authors="", abstract=None, published_date=None, url="u")],
    )

    def fetch(dois, *, mailto=None, client=None):
        raise CrossrefError("Crossref could not be reached.")

    assert backfill_citations(db_path, fetch=fetch, mailto=None) == 0
    assert list_papers(db_path, "all")[0].citation_data is None


def test_names_sent_in_capitals_are_written_as_names():
    paper = _paper(
        citation={
            "authors": [
                {"given": "ZACHARY P.", "family": "DICKSON"},
                {"given": "SEAN", "family": "MCDONALD-O'NEIL"},
            ]
        }
    )
    assert cite(paper, "apa").text.startswith("Dickson, Z. P., & McDonald-O'Neil, S. (2026). ")
    assert cite(paper, "chicago").text.startswith("Dickson, Zachary P., and Sean McDonald-O'Neil. 2026. ")
    # Initials alone stay as they are.
    assert cite(_paper(authors="J. R. Tolkien"), "chicago").text.startswith("Tolkien, J. R. 2026. ")
