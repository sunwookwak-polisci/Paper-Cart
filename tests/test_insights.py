import csv
import io
import sqlite3
import time
from codecs import BOM_UTF8
from datetime import date
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from paper_cart import db
from paper_cart.crossref import PaperHit
from paper_cart.web import create_app


DOIS = [f"10.1000/sample-{n}" for n in range(3)]
TITLE = 'Données, "résultats"\nand replication'
JOURNAL = "Journal of Examples"
ALL = {"unit": "month", "period": "all"}


def _seed(path):
    journal = db.subscribe_journal(path, title=JOURNAL, issns=("1234-5678",), publisher="")
    papers = [
        PaperHit(doi, title, "A. Example", None, None, f"https://doi.org/{doi}")
        for doi, title in zip(DOIS, [TITLE, "Second paper", "=Formula-like title"])
    ]
    db.upsert_papers(path, journal, JOURNAL, papers)


def _client(folder):
    return TestClient(create_app(folder), base_url="http://127.0.0.1")


def _csv(client, dataset="papers", **params):
    response = client.get(f"/insights/{dataset}.csv", params=params or ALL)
    assert response.status_code == 200
    assert response.content.startswith(BOM_UTF8)
    assert "attachment" in response.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"), newline="")))


def _move(client, dois, target, source):
    bulk = isinstance(dois, list)
    route = "/papers/status/bulk" if bulk else "/papers/status"
    response = client.post(route, data={"doi": dois, "status": target, "from": source},
                           follow_redirects=False)
    assert response.status_code == 303


def test_completion_survives_moves_bulk_and_restart(tmp_path, monkeypatch):
    client = _client(tmp_path)
    _seed(client.app.state.db_path)
    first = "2024-01-08T12:00:00+00:00"
    second = "2024-02-09T12:00:00+00:00"
    monkeypatch.setattr(db, "utcnow", lambda: first)
    _move(client, DOIS[0], "done", "new")
    _move(client, DOIS[0], "done", "new")
    assert [p["completed_at_utc"] for p in _csv(client)] == [first]
    _move(client, DOIS[0], "reading", "done")
    _move(client, DOIS[0], "done", "new")  # stale page
    assert db.list_papers(client.app.state.db_path, "reading")
    monkeypatch.setattr(db, "utcnow", lambda: second)
    _move(client, DOIS[:2], "done", "all")
    assert [p["completed_at_utc"] for p in _csv(client)] == [second, first]
    monkeypatch.setattr(db, "utcnow", lambda: "2024-03-10T12:00:00+00:00")
    client.post("/undo")
    assert [p["completed_at_utc"] for p in _csv(client)] == [first]
    client.post("/redo")
    _move(client, DOIS[0], "dismissed", "done")
    _move(client, DOIS[0], "removed", "dismissed")
    rows = _csv(client)
    assert [(p["doi"], p["completed_at_utc"]) for p in rows] == [
        (DOIS[1], second), (DOIS[0], first)
    ]
    assert _csv(_client(tmp_path)) == rows


def test_switch_to_legacy_library_backfills_done_once(tmp_path):
    current = _client(tmp_path)
    legacy = tmp_path / "older.sqlite"
    db.init_db(legacy)
    _seed(legacy)
    stamp = "2024-02-01T10:00:00+00:00"
    with sqlite3.connect(legacy) as conn:
        conn.execute("DROP INDEX papers_completed")
        conn.execute("ALTER TABLE papers DROP COLUMN first_completed_at")
        conn.execute("UPDATE papers SET status='done', status_updated_at=? WHERE doi=?",
                     (stamp, DOIS[1]))
    assert not _csv(current)
    def switch(name):
        response = current.post("/settings/libraries/active", data={"library": name})
        assert response.status_code == 200

    switch(legacy.name)
    assert [(p["doi"], p["completed_at_utc"]) for p in _csv(current)] == [(DOIS[1], stamp)]
    _move(current, DOIS[1], "reading", "done")
    switch("library.sqlite")
    assert not _csv(current)
    switch(legacy.name)
    assert [p["completed_at_utc"] for p in _csv(current)] == [stamp]


class _InsightLinks(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.cells = []
        self.papers = []
        self.downloads = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href", "")
        if attrs.get("class") == "heat-cell":
            self.cells.append((href, attrs["aria-label"]))
        elif href.startswith("https://doi.org/"):
            self.papers.append(href)
        elif href.startswith("/insights/") and ".csv?" in href:
            if "unit=month" not in href:
                self.downloads[href.split("?")[0]] = href


@pytest.fixture
def seoul_timezone(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("Changing the process time zone requires tzset")
    with monkeypatch.context() as local:
        local.setenv("TZ", "Asia/Seoul")
        time.tzset()
        try:
            yield
        finally:
            local.undo()
            time.tzset()


def test_calendar_chart_drilldown_and_downloads_agree(tmp_path, monkeypatch, seoul_timezone):
    # Local midnight on March 1 falls at 15:00 UTC on leap day.
    client = _client(tmp_path)
    _seed(client.app.state.db_path)
    stamps = ["2024-02-29T14:59:59+00:00", "2024-02-29T15:00:00+00:00",
              "2024-03-01T09:00:00+00:00"]
    for doi, stamp in zip(DOIS, stamps):
        monkeypatch.setattr(db, "utcnow", lambda: stamp)
        _move(client, doi, "done", "new")
    _assert_chart(client, {"unit": "day", "period": "2024-02"}, 29, 1)
    _assert_chart(client, {"unit": "day", "period": "2024-03"}, 31, 2)
    assert sum(int(row["papers_finished"]) for row in _csv(client, "totals", **{"unit": "month", "period": "2024"})) == 3
    rows = _csv(client)
    assert [row["completed_date_local"] for row in rows] == [
        "2024-03-01", "2024-03-01", "2024-02-29"
    ]
    assert rows[-1]["title"] == TITLE
    assert rows[0]["title"] == "'=Formula-like title"
    assert rows[-1]["journal"] == JOURNAL
    assert rows[-1]["authors"] == "A. Example"
    assert _csv(client, "totals")[0]["period_start"] == "2024-02-01"


def _assert_chart(client, params, bucket_count, total):
    page = client.get("/insights", params=params)
    assert page.status_code == 200
    assert f"<strong>{total}</strong>" in page.text
    links = _InsightLinks(page.text)
    totals = _csv(client, "totals", **params)
    assert len(links.cells) == len(totals) == bucket_count
    assert sum(int(row[f"papers_{params.get('activity', 'finished')}"]) for row in totals) == total
    for (href, label), row in zip(links.cells, totals):
        count = int(row[f"papers_{params.get('activity', 'finished')}"])
        assert row["period_start"] in href and f", {count} paper" in label
        detail = client.get(href)
        assert detail.status_code == 200
        filtered = _InsightLinks(detail.text)
        csv_url = filtered.downloads["/insights/papers.csv"]
        records = list(csv.DictReader(io.StringIO(client.get(csv_url).content.decode("utf-8-sig"))))
        assert len(records) == count
        assert filtered.papers == [record["url"] for record in records]
        assert filtered.downloads["/insights/totals.csv"] == links.downloads["/insights/totals.csv"]
        assert "Clear selection" in detail.text


def test_empty_library_and_filters(tmp_path):
    client = _client(tmp_path)
    page = client.get("/insights")
    assert page.status_code == 200
    assert date.today().isoformat()[:7] in page.text
    assert "No papers finished in this period." in page.text
    assert 'href="/insights"' in client.get("/").text
    assert not _csv(client)
    assert _csv(client, "totals") == [{
        "period_start": date.today().replace(day=1).isoformat(),
        "period_unit": "month", "papers_finished": "0"
    }]
    for params in ({"unit": "week"}, {"period": "2024-13"}, {"unit": "month", "period": "0000"}):
        assert client.get("/insights", params=params).status_code == 400


def test_legacy_start_uses_only_recoverable_move(tmp_path):
    path = tmp_path / "library.sqlite"
    db.init_db(path)
    _seed(path)
    stamp = "2024-01-01T12:00:00+00:00"
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX papers_started")
        conn.execute("ALTER TABLE papers DROP COLUMN first_started_at")
        conn.execute("UPDATE papers SET status='reading', status_updated_at=? WHERE doi=?",
                     (stamp, DOIS[0]))
        conn.execute("UPDATE papers SET status='done', first_completed_at=? WHERE doi=?",
                     (stamp, DOIS[1]))
    client = _client(tmp_path)
    rows = _csv(client, **ALL, activity="started")
    assert [(p["doi"], p["started_at_utc"]) for p in rows] == [(DOIS[0], stamp)]
    _move(client, DOIS[0], "done", "reading")
    assert _csv(_client(tmp_path), **ALL, activity="started") == rows


def test_first_start_bulk_replay_rereads_and_heatmap(tmp_path, monkeypatch, seoul_timezone):
    client = _client(tmp_path)
    _seed(client.app.state.db_path)
    first = "2024-02-29T14:59:59+00:00"
    second = "2024-02-29T15:00:00+00:00"
    monkeypatch.setattr(db, "utcnow", lambda: first)
    _move(client, DOIS[0], "reading", "new")
    _move(client, DOIS[0], "read_later", "reading")
    _move(client, DOIS[0], "reading", "new")  # stale
    _move(client, DOIS[2], "done", "new")  # skipped In Progress
    monkeypatch.setattr(db, "utcnow", lambda: second)
    _move(client, DOIS[:2], "reading", "all")
    _move(client, DOIS[:2], "reading", "all")  # repeated

    def records():
        return [(p["doi"], p["started_at_utc"]) for p in _csv(client, **ALL, activity="started")]

    assert records() == [(DOIS[1], second), (DOIS[0], first)]
    monkeypatch.setattr(db, "utcnow", lambda: "2024-03-05T18:00:00+00:00")
    client.post("/undo")
    assert records() == [(DOIS[0], first)]
    client.post("/redo")
    assert records() == [(DOIS[1], second), (DOIS[0], first)]
    _assert_chart(client, {"unit": "day", "period": "2024-03", "activity": "started"}, 31, 1)
    assert sum(int(row["papers_started"]) for row in _csv(client, "totals", **{"unit": "month", "period": "2024", "activity": "started"})) == 2
    assert len(_csv(client, **ALL)) == 1

    history = client.get("/insights?activity=started&unit=month&period=2024").text
    assert "moving 2 papers to In Progress" in history
    assert "activity=started" in history
    assert '<h1>In Progress</h1>' in client.get("/reading").text
    assert '<h1>To Read</h1>' in client.get("/later").text


def test_streaks_span_months_and_ignore_view_filters(tmp_path, monkeypatch, seoul_timezone):
    from paper_cart import insights

    class LocalDate(date):
        @classmethod
        def today(cls):
            return cls(2025, 1, 2)

    monkeypatch.setattr(insights, "date", LocalDate)
    client = _client(tmp_path)
    _seed(client.app.state.db_path)
    for doi, stamp in zip(DOIS, ["2024-12-30T15:00:00+00:00", "2024-12-31T15:00:00+00:00",
                                 "2024-12-31T15:00:01+00:00"]):
        monkeypatch.setattr(db, "utcnow", lambda: stamp)
        _move(client, doi, "reading", "new")
    page = client.get("/insights?unit=day&period=2024-11&activity=started")
    summary = page.context["insights"]
    assert not summary.papers
    assert (summary.current_streak, summary.longest_streak) == (2, 2)
    finishes = client.get("/insights").context["insights"]
    assert (finishes.current_streak, finishes.longest_streak) == (0, 0)

    days = [date(2024, 12, 31), date(2025, 1, 1), date(2025, 1, 4)]
    assert insights._streaks(days, date(2025, 1, 3)) == (0, 2)
    assert insights._streaks(days, date(2025, 1, 4)) == (1, 2)


def test_sorted_migration_and_distinct_papers(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    db.init_db(path)
    _seed(path)
    old = "2024-02-10T12:00:00+00:00"
    new = "2024-03-05T12:00:00+00:00"
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX papers_sorted")
        conn.execute("ALTER TABLE papers DROP COLUMN first_sorted_at")
        conn.execute("UPDATE papers SET status='read_later', status_updated_at=? WHERE doi=?",
                     (old, DOIS[0]))
    client = _client(tmp_path)
    filters = dict(ALL, activity="sorted")

    def records():
        return [(r["doi"], r["sorted_at_utc"]) for r in _csv(client, **filters)]

    assert records() == [(DOIS[0], old)]
    monkeypatch.setattr(db, "utcnow", lambda: new)
    _move(client, DOIS[0], "reading", "read_later")
    _move(client, DOIS[2], "done", "new")
    _move(client, DOIS[:2], "read_later", "all")
    _move(client, DOIS[:2], "read_later", "all")
    assert records() == [(DOIS[1], new), (DOIS[0], old)]
    client.post("/undo")
    assert records() == [(DOIS[0], old)]
    client.post("/redo")
    assert records() == [(DOIS[1], new), (DOIS[0], old)]
    _move(client, DOIS[1], "done", "read_later")
    assert _csv(_client(tmp_path), **filters) == _csv(client, **filters)
    assert sum(int(row["papers_sorted"]) for row in _csv(client, "totals", **{"unit": "month", "period": "2024", "activity": "sorted"})) == 2


def test_contribution_graph_year_leap_day_and_week_alignment(tmp_path):
    client = _client(tmp_path)
    page = client.get("/insights?period=2024&activity=sorted")
    assert page.status_code == 200
    links = _InsightLinks(page.text)
    assert len(links.cells) == 366
    # Jan 1, 2024 was Monday (row 3). Jan 7 starts the next Sunday column.
    assert 'style="grid-column:2;grid-row:3" href="/insights?unit=day&amp;period=2024&amp;activity=sorted&amp;selected=2024-01-01' in page.text
    assert 'style="grid-column:3;grid-row:2" href="/insights?unit=day&amp;period=2024&amp;activity=sorted&amp;selected=2024-01-07' in page.text
    assert '2024-02-29' in links.cells[59][0]
    rows = _csv(client, "totals", period="recent", activity="sorted")
    assert len(rows) == 365 and rows[-1]["period_start"] == date.today().isoformat()
    assert len(_InsightLinks(client.get("/insights").text).cells) == len(rows)


def test_monthly_view_links_open_daily_graph_and_keep_monthly_export(tmp_path):
    client = _client(tmp_path)
    page = client.get("/insights?unit=month&period=2024&selected=2024-02-01&activity=sorted")
    assert len(_InsightLinks(page.text).cells) == 29
    assert 'aria-label="Chart interval"' not in page.text
    assert "Download monthly totals CSV" in page.text
    assert _csv(client, "totals", unit="month", period="2024-02", activity="sorted") == [
        {"period_start": "2024-02-01", "period_unit": "month", "papers_sorted": "0"}
    ]
    assert client.get("/insights?period=all").context["insights"].unit == "day"
