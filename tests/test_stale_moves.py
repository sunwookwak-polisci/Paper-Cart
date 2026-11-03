"""Papers leave a list only when the user moves them from that list."""

import io
import os

from fastapi.testclient import TestClient

from paper_cart.crossref import PaperHit
from paper_cart.db import list_papers, move_papers_from, subscribe_journal, upsert_papers
from paper_cart.web import create_app, start_startup_refresh


def _app(folder, count=3):
    app = create_app(folder, search=lambda *a, **k: [], fetch=lambda *a, **k: [])
    db_path = app.state.db_path
    journal_id = subscribe_journal(db_path, title="Example Journal", issns=("1234-5678",), publisher="")
    upsert_papers(
        db_path,
        journal_id,
        "Example Journal",
        [
            PaperHit(
                doi=f"10.1000/p{n}",
                title=f"Paper {n}",
                authors="",
                abstract=None,
                published_date="2026-09-01",
                url=f"https://doi.org/10.1000/p{n}",
            )
            for n in range(count)
        ],
    )
    return app, TestClient(app, base_url="http://127.0.0.1")


def _dois(app, status):
    return sorted(paper.doi for paper in list_papers(app.state.db_path, status))


def test_bulk_from_an_old_new_page_leaves_papers_saved_elsewhere(tmp_path):
    app, client = _app(tmp_path)
    client.post("/papers/status", data={"doi": "10.1000/p0", "status": "read_later", "from": "new"})
    # An older tab still lists p0 under New; Select all shown, then Dismiss.
    response = client.post(
        "/papers/status/bulk",
        data={"status": "dismissed", "from": "new", "doi": ["10.1000/p0", "10.1000/p1", "10.1000/p2"]},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/?moved_elsewhere=1"
    assert _dois(app, "read_later") == ["10.1000/p0"]
    assert _dois(app, "dismissed") == ["10.1000/p1", "10.1000/p2"]
    page = client.get(response.headers["location"])
    assert "1 paper was already in another list, so it was left there." in page.text
    # Undo takes back only what really moved.
    client.post("/undo", data={"next": "/"})
    assert _dois(app, "new") == ["10.1000/p1", "10.1000/p2"]
    assert _dois(app, "read_later") == ["10.1000/p0"]


def test_single_button_on_an_old_page_does_not_pull_a_paper_out_of_done(tmp_path):
    app, client = _app(tmp_path)
    client.post("/papers/status", data={"doi": "10.1000/p1", "status": "done", "from": "new"})
    response = client.post(
        "/papers/status",
        data={"doi": "10.1000/p1", "status": "dismissed", "from": "new", "next": "/?q=Paper"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/?q=Paper&moved_elsewhere=1"
    assert _dois(app, "done") == ["10.1000/p1"]
    assert _dois(app, "dismissed") == []


def test_a_paper_already_in_the_target_list_is_not_reported(tmp_path):
    app, client = _app(tmp_path)
    client.post("/papers/status", data={"doi": "10.1000/p1", "status": "dismissed", "from": "new"})
    response = client.post(
        "/papers/status",
        data={"doi": "10.1000/p1", "status": "dismissed", "from": "new"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"


def test_remove_from_an_old_dismissed_page_skips_a_paper_moved_back_to_new(tmp_path):
    app, client = _app(tmp_path)
    client.post("/papers/status/bulk", data={"status": "dismissed", "from": "new", "doi": ["10.1000/p0", "10.1000/p1"]})
    client.post("/papers/status", data={"doi": "10.1000/p0", "status": "new", "from": "dismissed"})
    response = client.post(
        "/papers/status/bulk",
        data={"status": "removed", "from": "dismissed", "doi": ["10.1000/p0", "10.1000/p1"], "next": "/dismissed"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dismissed?moved_elsewhere=1"
    assert _dois(app, "removed") == ["10.1000/p1"]
    assert "10.1000/p0" in _dois(app, "new")


def test_moves_without_a_source_list_still_work(tmp_path):
    app, client = _app(tmp_path)
    client.post("/papers/status", data={"doi": "10.1000/p0", "status": "done"})
    assert _dois(app, "done") == ["10.1000/p0"]
    found, changes, elsewhere = move_papers_from(app.state.db_path, ["10.1000/p0", "10.1000/x"], "new", "done")
    assert (found, len(changes), elsewhere) == (1, 1, 0)
    assert client.post("/papers/status", data={"doi": "10.1000/p0", "status": "done", "from": "nope"}).status_code == 400


def test_list_pages_carry_their_list_and_are_not_cached(tmp_path):
    app, client = _app(tmp_path)
    client.post("/papers/status", data={"doi": "10.1000/p2", "status": "read_later", "from": "new"})
    for path in ("/", "/reading", "/later", "/done", "/dismissed", "/removed"):
        assert client.get(path).headers["cache-control"] == "no-store"
    assert 'name="from" value="read_later"' in client.get("/later").text
    client.post("/papers/status", data={"doi": "10.1000/p2", "status": "new", "from": "read_later"})
    page = client.get("/")
    assert page.text.count('name="from" value="new"') == 4  # three cards and the bulk bar
    assert page.text.count('autocomplete="off" data-bulk-pick') == 3


def test_importing_over_the_active_library_forgets_undo(tmp_path):
    app, client = _app(tmp_path)
    client.post("/papers/status", data={"doi": "10.1000/p0", "status": "dismissed", "from": "new"})
    other = tmp_path / "other"
    other.mkdir()
    other_app, other_client = _app(other)
    other_client.post("/papers/status", data={"doi": "10.1000/p0", "status": "dismissed", "from": "new"})
    name = app.state.db_path.name
    response = client.post(
        "/settings/libraries/import",
        files={"upload": (name, io.BytesIO(other_app.state.db_path.read_bytes()), "application/octet-stream")},
        data={"name": name, "confirm": "yes"},
        follow_redirects=False,
    )
    assert "active=1" in response.headers["location"]
    assert app.state.history.labels(app.state.db_path) == ("", "")
    client.post("/undo", data={"next": "/"})
    assert _dois(app, "dismissed") == ["10.1000/p0"]


def test_a_missing_library_file_is_not_replaced_by_an_empty_one(tmp_path):
    app, _ = _app(tmp_path)
    (tmp_path / "active-library").write_text("library.sqlite\n", encoding="utf-8")
    os.replace(app.state.db_path, tmp_path / "moved.sqlite.bak")
    reopened = create_app(tmp_path, search=lambda *a, **k: [], fetch=lambda *a, **k: [])
    assert not (tmp_path / "library.sqlite").exists()
    start_startup_refresh(reopened)
    client = TestClient(reopened, base_url="http://127.0.0.1")
    first = client.get("/", follow_redirects=False)
    assert first.headers["location"] == "/settings?unavailable=1"
    page = client.get("/settings?unavailable=1")
    assert "library.sqlite is not in this folder." in page.text
    assert not (tmp_path / "library.sqlite").exists()


def test_a_saved_choice_that_is_gone_does_not_open_another_file_quietly(tmp_path):
    app, client = _app(tmp_path)
    (tmp_path / "active-library").write_text("thesis.sqlite\n", encoding="utf-8")
    reopened = create_app(tmp_path, search=lambda *a, **k: [], fetch=lambda *a, **k: [])
    page = TestClient(reopened, base_url="http://127.0.0.1").get("/settings")
    assert "thesis.sqlite is not in this folder." in page.text
    assert 'data-library="library.sqlite"' in page.text


def test_an_icloud_placeholder_is_not_replaced_by_an_empty_library(tmp_path):
    app, _ = _app(tmp_path)
    os.replace(app.state.db_path, tmp_path / ".library.sqlite.icloud")
    reopened = create_app(tmp_path, search=lambda *a, **k: [], fetch=lambda *a, **k: [])
    assert reopened.state.db_path == tmp_path / "library.sqlite"
    assert not (tmp_path / "library.sqlite").exists()


def test_an_icloud_folder_names_the_library_placeholder_not_other_files(tmp_path):
    app, _ = _app(tmp_path)
    os.replace(app.state.db_path, tmp_path / ".library.sqlite.icloud")
    (tmp_path / ".active-library.icloud").write_text("")
    (tmp_path / ".config.toml.icloud").write_text("")
    reopened = create_app(tmp_path, search=lambda *a, **k: [], fetch=lambda *a, **k: [])
    assert reopened.state.db_path == tmp_path / "library.sqlite"


def test_a_new_folder_still_gets_a_new_library(tmp_path):
    app = create_app(tmp_path / "fresh", search=lambda *a, **k: [], fetch=lambda *a, **k: [])
    assert app.state.db_path.is_file()


def test_all_tab_moves_check_each_paper_and_skip_the_trash(tmp_path):
    app, client = _app(tmp_path)
    page = client.get("/all").text
    assert 'name="from" value="new"' in page  # each card names its own list
    client.post("/papers/status", data={"doi": "10.1000/p0", "status": "done", "from": "new"})
    # The All page still shows p0 under New; its Dismiss button is now out of date.
    stale = client.post(
        "/papers/status",
        data={"doi": "10.1000/p0", "status": "dismissed", "from": "new", "next": "/all"},
        follow_redirects=False,
    )
    assert stale.headers["location"] == "/all?moved_elsewhere=1"
    assert _dois(app, "done") == ["10.1000/p0"]
    # Bulk from All moves papers in any list, but not ones sent to the trash since.
    client.post("/papers/status", data={"doi": "10.1000/p1", "status": "dismissed", "from": "new"})
    client.post("/papers/status", data={"doi": "10.1000/p1", "status": "removed", "from": "dismissed"})
    bulk = client.post(
        "/papers/status/bulk",
        data={"status": "read_later", "from": "all", "doi": ["10.1000/p0", "10.1000/p1", "10.1000/p2"], "next": "/all"},
        follow_redirects=False,
    )
    assert bulk.headers["location"] == "/all?moved_elsewhere=1"
    assert _dois(app, "read_later") == ["10.1000/p0", "10.1000/p2"]
    assert _dois(app, "removed") == ["10.1000/p1"]


def test_a_hand_typed_moved_elsewhere_count_is_ignored(tmp_path):
    _, client = _app(tmp_path)
    for value in ("\u00b2", "9" * 5000, "-1", "abc"):
        page = client.get("/", params={"moved_elsewhere": value})
        assert page.status_code == 200
        assert "data-moved-elsewhere" not in page.text
