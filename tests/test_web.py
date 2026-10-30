import threading
import time

from paper_cart.crossref import JournalHit, PaperHit, select_recent_issues
from paper_cart.db import list_journals_by_rank, list_papers, subscribe_journal, upsert_papers
from paper_cart.web import create_app, safe_next


def test_safe_next_rejects_offsite_urls():
    assert safe_next("/later") == "/later"
    assert safe_next("https://example.com") == "/"
    assert safe_next("//example.com") == "/"


def test_header_shows_running_version(tmp_path):
    from fastapi.testclient import TestClient

    from paper_cart import __version__

    client = TestClient(create_app(tmp_path, search=_search, fetch=_fetch), base_url="http://127.0.0.1")
    for path in ("/", "/journals", "/settings"):
        assert f'<span class="app-version">v{__version__}</span>' in client.get(path).text


def test_theme_switch_and_palette_are_served(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(
        create_app(tmp_path, search=_search, fetch=_fetch), base_url="http://127.0.0.1"
    )
    page = client.get("/")
    assert 'src="/static/theme.js"' in page.text
    assert 'aria-label="Color theme"' in page.text
    assert 'data-theme-toggle' in page.text
    assert 'aria-haspopup="dialog"' in page.text
    assert 'id="theme-options" class="theme-options" role="dialog" aria-label="Color theme" hidden' in page.text
    assert 'aria-label="Appearance"' in page.text
    assert 'aria-label="Light theme"' in page.text
    assert 'aria-label="Dark theme"' in page.text
    assert 'data-theme-mode="light"' in page.text
    assert 'data-theme-mode="dark"' in page.text
    assert 'data-theme-mode="system"' in page.text
    assert 'data-theme-light="alucard"' in page.text
    assert "Alucard (Dracula Light)" in page.text
    assert 'data-theme-light="tokyo-light"' in page.text
    assert 'data-theme-light="ayu-light"' in page.text
    assert 'data-theme-light="solarized-light"' in page.text
    assert 'data-theme-dark="dracula"' in page.text
    assert 'data-theme-dark="tokyo-night"' in page.text
    assert 'data-theme-dark="ayu-dark"' in page.text
    assert 'data-theme-dark="solarized-dark"' in page.text
    assert "Catppuccin" not in page.text
    assert 'aria-label="Font"' in page.text
    assert 'data-font="serif"' in page.text
    assert 'data-font="sans"' in page.text
    assert "Serif is Source Serif 4. Sans is Source Sans 3." in page.text
    assert "System uses your light or dark theme to match this device." in page.text
    assert "data-theme-option=" not in page.text
    assert "prefers-color-scheme: dark" in page.text
    assert "paper-cart-font" in page.text
    assert ">Update</button>" in page.text or "Updating" in page.text
    menu = page.text.split('id="theme-options"', 1)[1].split("</header>", 1)[0]
    appearance, font = menu.split('aria-label="Font"', 1)
    assert menu.index('data-theme-mode="light"') < menu.index('data-theme-mode="dark"')
    assert menu.index('data-theme-mode="dark"') < menu.index('data-theme-mode="system"')
    assert menu.index('data-theme-mode="system"') < menu.index('aria-label="Light theme"')
    assert menu.index('aria-label="Light theme"') < menu.index('aria-label="Dark theme"')
    assert 'class="appearance-modes"' in appearance
    assert 'aria-label="Light theme"' in appearance
    assert 'aria-label="Dark theme"' in appearance
    assert "appearance-modes" not in font
    assert "Source Serif 4" in font

    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert "#fffbeb" in css.text
    assert "#282a36" in css.text
    assert "#644ac9" in css.text
    assert "#bd93f9" in css.text
    assert "#e6e7ed" in css.text
    assert "#1a1b26" in css.text
    assert "#7aa2f7" in css.text
    assert "#2959aa" in css.text
    assert "#fafafa" in css.text
    assert "#0f1419" in css.text
    assert "#ff6a00" in css.text
    assert "#f29718" in css.text
    assert "#fdf6e3" in css.text
    assert "#002b36" in css.text
    assert "#268bd2" in css.text
    assert 'html[data-theme="dracula"]' in css.text
    assert 'html[data-theme="tokyo-night"]' in css.text
    assert 'html[data-theme="ayu-light"]' in css.text
    assert 'html[data-theme="ayu-dark"]' in css.text
    assert 'html[data-theme="catppuccin-latte"]' not in css.text
    assert 'html[data-theme="catppuccin-mocha"]' not in css.text
    assert 'html[data-theme="solarized-light"]' in css.text
    assert 'html[data-theme="solarized-dark"]' in css.text
    assert "Source Serif 4" in css.text
    assert "Newsreader" not in css.text
    assert "Source Sans 3" in css.text
    assert "/static/fonts/source-serif-4-latin.woff2" in css.text
    assert "/static/fonts/source-sans-3-latin.woff2" in css.text
    assert "fonts.googleapis.com" not in css.text
    assert "Iowan Old Style" not in css.text
    assert "Avenir Next" not in css.text
    assert "background: var(--ink)" not in css.text
    assert "background: var(--select)" in css.text
    assert "color: var(--select-ink)" in css.text
    for name in (
        "source-serif-4-latin.woff2",
        "source-serif-4-latin-ext.woff2",
        "source-sans-3-latin.woff2",
        "source-sans-3-latin-ext.woff2",
    ):
        font_file = client.get(f"/static/fonts/{name}")
        assert font_file.status_code == 200
        assert font_file.content[:4] == b"wOF2"
    bulk = css.text.split(".bulk-bar {", 1)[1].split("}", 1)[0]
    card = css.text.split(".card {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid var(--line)" in card
    assert "border-radius" in card
    assert "background: var(--card)" in card
    assert "border: 0" in bulk
    assert "border-radius: 0" in bulk
    assert "box-shadow: none" in bulk
    assert "background: var(--paper)" in bulk
    assert "1px solid var(--line)" not in bulk

    js = client.get("/static/theme.js")
    assert js.status_code == 200
    assert "paper-cart-theme" in js.text
    assert "tokyo-light" in js.text
    assert "tokyo-night" in js.text
    assert "ayu-light" in js.text
    assert "ayu-dark" in js.text
    assert "catppuccin-latte" in js.text
    assert "catppuccin-mocha" in js.text
    assert 'if (field === "light") pref.mode = "light"' not in js.text
    assert 'if (field === "dark") pref.mode = "dark"' not in js.text
    assert "/appearance" in js.text
    assert "solarized-light" in js.text
    assert "solarized-dark" in js.text
    assert "paper-cart-font" in js.text
    assert "data-font" in js.text
    assert "data-theme-toggle" in js.text
    assert "data-theme-mode" in js.text
    assert "data-theme-light" in js.text
    assert "data-theme-dark" in js.text
    assert "prefers-color-scheme" in js.text
    assert "JSON.stringify" in js.text
    assert "aria-expanded" in js.text
    assert "localStorage" in js.text


def test_appearance_persists_across_reopen(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(
        create_app(tmp_path, search=_search, fetch=_fetch), base_url="http://127.0.0.1"
    )
    saved = client.post(
        "/appearance",
        data={"mode": "dark", "light": "ayu-light", "dark": "ayu-dark", "font": "sans"},
    )
    assert saved.status_code == 204
    page = client.get("/")
    assert 'data-theme-preference="dark"' in page.text
    assert 'data-theme="ayu-dark"' in page.text
    assert 'data-theme-light="ayu-light"' in page.text
    assert 'data-theme-dark="ayu-dark"' in page.text
    assert 'data-font="sans"' in page.text

    reopened = TestClient(
        create_app(tmp_path, search=_search, fetch=_fetch), base_url="http://127.0.0.1"
    )
    again = reopened.get("/")
    assert 'data-theme-preference="dark"' in again.text
    assert 'data-theme="ayu-dark"' in again.text
    assert 'data-font="sans"' in again.text


def test_catppuccin_appearance_falls_back(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(
        create_app(tmp_path, search=_search, fetch=_fetch), base_url="http://127.0.0.1"
    )
    saved = client.post(
        "/appearance",
        data={
            "mode": "light",
            "light": "catppuccin-latte",
            "dark": "catppuccin-mocha",
            "font": "serif",
        },
    )
    assert saved.status_code == 204
    page = client.get("/")
    assert 'data-theme-preference="light"' in page.text
    assert 'data-theme="alucard"' in page.text
    assert 'data-theme-light="alucard"' in page.text
    assert 'data-theme-dark="dracula"' in page.text
    assert "Catppuccin" not in page.text


def test_subscribe_update_and_progress(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    client = TestClient(app, base_url="http://127.0.0.1")

    search = client.get("/journals?q=example")
    assert search.status_code == 200
    assert "Example Journal" in search.text
    assert "Add to cart" in search.text

    missed = client.post(
        "/journals/cart",
        data={
            "q": "example",
            "title": "Example Journal",
            "publisher": "Example Press",
            "issns": "1234-5678",
        },
        follow_redirects=False,
    )
    assert missed.status_code == 303
    assert missed.headers["location"] == "/journals?q=example&notice=select"
    assert "Select at least one journal." in client.get(missed.headers["location"]).text

    added = client.post(
        "/journals/cart",
        data={
            "q": "example",
            "pick": "0",
            "title": "Example Journal",
            "publisher": "Example Press",
            "issns": "1234-5678",
        },
        follow_redirects=False,
    )
    assert added.status_code == 303
    assert added.headers["location"] == "/journals?q=example"
    cart = client.get(added.headers["location"])
    assert "In cart" in cart.text
    assert 'action="/journals/checkout"' in cart.text

    subscribed = client.post("/journals/checkout", follow_redirects=False)
    assert subscribed.status_code == 303
    assert subscribed.headers["location"] == "/journals?subscribed=1"
    assert app.state.refresh_thread is not None
    app.state.refresh_thread.join(timeout=5)

    inbox = client.get("/")
    assert "A real paper" in inbox.text
    assert "1 new paper from 1 journal." in inbox.text
    assert "Hello from the abstract" in inbox.text

    moved = client.post(
        "/papers/status",
        data={"doi": "10.1000/example", "status": "read_later", "next": "/later"},
        follow_redirects=False,
    )
    assert moved.headers["location"] == "/later"
    assert "A real paper" in client.get("/later").text
    assert "A real paper" not in client.get("/").text

    client.post(
        "/papers/status",
        data={"doi": "10.1000/example", "status": "reading", "next": "/reading"},
        follow_redirects=False,
    )
    refreshed = client.post("/refresh", follow_redirects=False)
    assert refreshed.status_code == 303
    reading = client.get("/reading")
    assert "A real paper" in reading.text
    assert "A real paper" not in client.get("/").text
    assert 'aria-label="Remove"' not in reading.text
    assert 'class="trash-link"' in reading.text
    assert ">Removal<" not in reading.text

    blocked = client.post(
        "/papers/status",
        data={"doi": "10.1000/example", "status": "removed", "next": "/reading"},
    )
    assert blocked.status_code == 400
    assert "A real paper" in client.get("/reading").text

    client.post(
        "/papers/status",
        data={"doi": "10.1000/example", "status": "dismissed", "next": "/dismissed"},
        follow_redirects=False,
    )
    dismissed = client.get("/dismissed")
    assert "A real paper" in dismissed.text
    assert 'aria-label="Remove"' in dismissed.text
    assert ">Removal<" not in dismissed.text
    removed = client.post(
        "/papers/status",
        data={"doi": "10.1000/example", "status": "removed", "next": "/dismissed"},
        follow_redirects=False,
    )
    assert removed.status_code == 303
    assert removed.headers["location"] == "/dismissed"
    assert "A real paper" not in client.get("/dismissed").text
    removed_page = client.get("/removed")
    assert "<h1>Removed</h1>" in removed_page.text
    assert "A real paper" in removed_page.text
    assert 'aria-label="Remove"' not in removed_page.text
    restored = client.post(
        "/papers/status",
        data={"doi": "10.1000/example", "status": "done", "next": "https://example.com"},
        follow_redirects=False,
    )
    assert restored.headers["location"] == "/"
    assert "A real paper" in client.get("/done").text
    assert "A real paper" not in client.get("/removed").text

    unknown = client.post(
        "/papers/status",
        data={"doi": "10.1000/example", "status": "archived", "next": "/"},
    )
    assert unknown.status_code == 400

    journals = client.get("/journals")
    assert "Unsubscribe" in journals.text
    client.post("/journals/1/unsubscribe", follow_redirects=False)
    assert "No journals yet." in client.get("/journals").text
    assert "A real paper" in client.get("/done").text


def test_checkout_returns_before_crossref(tmp_path):
    from fastapi.testclient import TestClient

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def fetch(issns, start, *, mailto=None, client=None, pause=None):
        started.set()
        release.wait(timeout=3)
        finished.set()
        return []

    app = create_app(tmp_path, search=_search, fetch=fetch)
    client = TestClient(app, base_url="http://127.0.0.1")
    added = client.post(
        "/journals/cart",
        data={
            "q": "example",
            "pick": "0",
            "title": "Example Journal",
            "publisher": "Example Press",
            "issns": "1234-5678",
        },
        follow_redirects=False,
    )
    assert added.status_code == 303
    started_at = time.monotonic()
    subscribed = client.post("/journals/checkout", follow_redirects=False)
    elapsed = time.monotonic() - started_at
    assert subscribed.status_code == 303
    assert subscribed.headers["location"] == "/journals?subscribed=1"
    assert elapsed < 1
    assert started.wait(timeout=2)
    assert not finished.is_set()
    release.set()
    app.state.refresh_thread.join(timeout=5)
    assert finished.is_set()


def test_cart_keeps_journals_across_searches(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, search=_catalog_search, fetch=_fetch)
    client = TestClient(app, base_url="http://127.0.0.1")
    first = client.post(
        "/journals/cart",
        data={
            "q": "example",
            "pick": "0",
            "title": "Example Journal",
            "publisher": "Example Press",
            "issns": "1234-5678",
        },
        follow_redirects=False,
    )
    assert first.headers["location"] == "/journals?q=example"
    second = client.post(
        "/journals/cart",
        data={
            "q": "other",
            "pick": "0",
            "title": "Other Journal",
            "publisher": "Other Press",
            "issns": "9999-999X",
        },
        follow_redirects=False,
    )
    assert second.headers["location"] == "/journals?q=other"
    cart = client.get("/journals?q=other")
    assert "Example Journal" in cart.text
    assert "Other Journal" in cart.text
    assert cart.text.index("Example Journal") < cart.text.index("Other Journal")
    item_id = cart.text.split('name="item_id" value="', 1)[1].split('"', 1)[0]
    removed = client.post(
        "/journals/cart/remove",
        data={"item_id": item_id, "q": "other"},
        follow_redirects=False,
    )
    assert removed.headers["location"] == "/journals?q=other"
    remaining = client.get(removed.headers["location"])
    cart_html = remaining.text.split("<h2>Subscribed</h2>", 1)[0]
    assert "Example Journal" not in cart_html
    assert "Other Journal" in cart_html


def test_paper_list_search_and_group_order(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    db_path = tmp_path / "library.sqlite"
    alpha = subscribe_journal(
        db_path,
        title="Alpha Journal",
        issns=("1111-1111",),
        publisher="",
    )
    beta = subscribe_journal(
        db_path,
        title="Beta Journal",
        issns=("2222-2222",),
        publisher="",
    )
    upsert_papers(
        db_path,
        alpha,
        "Alpha Journal",
        [
            _hit("10.1000/old", "Older paper", "2026-01-01", "Ada Lovelace", "neurons in the abstract"),
            _hit("10.1000/late", "November paper", "2026-11-01", "Ada Lovelace", "a later note"),
        ],
    )
    upsert_papers(
        db_path,
        beta,
        "Beta Journal",
        [
            _hit("10.1000/new", "August paper", "2026-08-01", "Grace Hopper", "compilers"),
            _hit("10.1000/dec", "December essay", "2026-12-01", "Grace Hopper", "seasonal note"),
        ],
    )
    client = TestClient(app, base_url="http://127.0.0.1")

    flat = client.get("/")
    assert flat.text.index("December essay") < flat.text.index("November paper")
    assert flat.text.index("November paper") < flat.text.index("August paper")
    assert flat.text.index("August paper") < flat.text.index("Older paper")
    assert 'class="journal-name"' not in flat.text
    assert "Alpha Journal" in flat.text

    matched = client.get("/?q=neurons+abstract")
    assert "Older paper" in matched.text
    assert "August paper" not in matched.text
    assert "No papers matched." in client.get("/?q=missing-term").text
    assert "Older paper" not in client.get("/reading?q=neurons").text

    grouped = client.post("/view", data={"group": "1", "next": "/?q=neurons"}, follow_redirects=False)
    assert grouped.headers["location"] == "/?q=neurons"
    by_date = client.get("/")
    assert 'class="journal-name"' in by_date.text
    assert by_date.text.index("Beta Journal") < by_date.text.index("Alpha Journal")
    assert by_date.text.index("November paper") < by_date.text.index("Older paper")
    filtered = client.get("/?q=paper")
    assert "December essay" not in filtered.text
    assert filtered.text.index("Alpha Journal") < filtered.text.index("Beta Journal")

    client.post("/view", data={"group_sort": "alpha", "next": "/"}, follow_redirects=False)
    by_name = client.get("/")
    assert by_name.text.index("Alpha Journal") < by_name.text.index("Beta Journal")
    assert 'aria-pressed="true"' in client.get("/reading").text

    client.post("/view", data={"group_sort": "custom", "next": "/"}, follow_redirects=False)
    custom = client.get("/")
    assert "Journal order" in custom.text
    assert 'id="journal-order-panel" open' in custom.text
    assert 'aria-label="Move Beta Journal up"' in custom.text
    assert ">Up<" not in custom.text
    assert ">Down<" not in custom.text
    assert custom.text.index("Beta Journal") < custom.text.index("Alpha Journal")
    ranks = list_journals_by_rank(db_path)
    assert [journal.title for journal in ranks] == ["Beta Journal", "Alpha Journal"]
    client.post(
        "/journals/order",
        data={"journal_id": str(alpha), "direction": "up", "next": "/"},
        follow_redirects=False,
    )
    reordered = client.get("/")
    assert reordered.text.index("Alpha Journal") < reordered.text.index("Beta Journal")
    assert [journal.title for journal in list_journals_by_rank(db_path)] == [
        "Alpha Journal",
        "Beta Journal",
    ]
    client.post(
        "/journals/order",
        data={"order": [str(beta), str(alpha)], "next": "/"},
        follow_redirects=False,
    )
    assert [journal.title for journal in list_journals_by_rank(db_path)] == [
        "Beta Journal",
        "Alpha Journal",
    ]
    folded = client.post("/view", data={"order_open": "0", "next": "/"}, follow_redirects=False)
    assert folded.status_code == 303
    folded_page = client.get("/")
    assert '<details class="order-panel" id="journal-order-panel">' in folded_page.text
    assert 'id="journal-order-panel" open' not in folded_page.text
    assert "Journal order" in folded_page.text
    assert folded_page.text.index("Beta Journal") < folded_page.text.index("Alpha Journal")
    opened = client.post("/view", data={"order_open": "1", "next": "/"}, follow_redirects=False)
    assert opened.status_code == 303
    assert 'id="journal-order-panel" open' in client.get("/").text


def test_expand_abstracts_toggle_is_remembered(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    db_path = tmp_path / "library.sqlite"
    journal_id = subscribe_journal(db_path, title="Example Journal", issns=("1234-5678",), publisher="")
    client = TestClient(app, base_url="http://127.0.0.1")
    assert "Expand abstracts" not in client.get("/").text

    upsert_papers(
        db_path,
        journal_id,
        "Example Journal",
        [_hit("10.1000/a", "Paper A", "2026-09-01", "Ada Lovelace", "about neurons")],
    )
    folded = client.get("/")
    assert "Expand abstracts" in folded.text
    assert '<details class="abstract">' in folded.text
    assert 'name="abstracts" value="1"' in folded.text

    expanded = client.post("/view", data={"abstracts": "1", "next": "/"}, follow_redirects=False)
    assert expanded.headers["location"] == "/"
    page = client.get("/")
    assert '<details class="abstract" open>' in page.text
    assert 'name="abstracts" value="0"' in page.text
    assert '<details class="abstract" open>' in client.get("/?q=neurons").text

    client.post("/view", data={"abstracts": "0", "next": "/"}, follow_redirects=False)
    assert '<details class="abstract">' in client.get("/").text


def test_export_abstracts_fetches_older_issues_without_changing_library(tmp_path):
    from fastapi.testclient import TestClient

    def fetch_issues(issns, issue_count, *, mailto=None, client=None, pause=None):
        if issns == ("1234-5678",):
            papers = [
                _hit(
                    "10.1000/new-issue",
                    "Fresh paper",
                    "2026-10-01",
                    "Ada Lovelace",
                    "Hello from October",
                    volume="12",
                    issue="4",
                    issue_date="2026-10",
                ),
                _hit(
                    "10.1000/old-issue",
                    "Archive paper",
                    "2026-01-01",
                    "Ada Lovelace",
                    "Hello from January",
                    volume="12",
                    issue="3",
                    issue_date="2026-01",
                ),
                _hit(
                    "10.1000/older",
                    "Too old",
                    "2025-12-01",
                    "Ada Lovelace",
                    "Should be omitted",
                    volume="12",
                    issue="2",
                    issue_date="2025-12",
                ),
            ]
        else:
            papers = [
                _hit(
                    "10.1000/beta",
                    "Beta paper",
                    "2026-09-01",
                    "Grace Hopper",
                    "Beta abstract",
                    volume="1",
                    issue="8",
                    issue_date="2026-09",
                )
            ]
        return select_recent_issues(papers, issue_count)

    app = create_app(tmp_path, search=_search, fetch=_fetch, fetch_issues=fetch_issues)
    db_path = tmp_path / "library.sqlite"
    example = subscribe_journal(
        db_path,
        title="Example Journal",
        issns=("1234-5678",),
        publisher="Example Press",
    )
    other = subscribe_journal(
        db_path,
        title="Other Journal",
        issns=("9999-999X",),
        publisher="Other Press",
    )
    upsert_papers(
        db_path,
        example,
        "Example Journal",
        [_hit("10.1000/library", "Already new", "2026-10-01", "Ada Lovelace", "library abstract")],
    )
    client = TestClient(app, base_url="http://127.0.0.1")

    page = client.get("/journals")
    assert "Export abstracts" in page.text
    assert "Markdown file" in page.text
    assert 'action="/journals/export"' in page.text
    assert "Number of recent issues" in page.text
    assert 'src="/static/export.js"' in page.text

    missed = client.post("/journals/export", data={"issues": "2"}, follow_redirects=False)
    assert missed.status_code == 303
    assert missed.headers["location"] == "/journals?notice=select_export"
    missed_page = client.get(missed.headers["location"])
    assert "Select at least one journal to export." in missed_page.text
    assert 'data-notice' in missed_page.text

    invalid = client.post(
        "/journals/export",
        data={"journal_id": str(example), "issues": "0"},
        follow_redirects=False,
    )
    assert invalid.headers["location"] == "/journals?notice=issues"
    assert "Choose between 1 and 30 issues." in client.get(invalid.headers["location"]).text

    downloaded = client.post(
        "/journals/export",
        data={"journal_id": [str(example), str(other)], "issues": "2"},
        follow_redirects=False,
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-disposition"] == 'attachment; filename="journal-abstracts.md"'
    assert downloaded.headers["content-type"].startswith("text/markdown")
    body = downloaded.text
    assert "# Example Journal" in body
    assert "# Other Journal" in body
    assert "### [Fresh paper](https://doi.org/10.1000/new-issue)" in body
    assert "## Volume 12, Issue 3 (2026-01)" in body
    assert "Archive paper" in body
    assert "Hello from January" in body
    assert "Too old" not in body
    assert "Should be omitted" not in body
    assert "Beta paper" in body
    assert "Already new" not in body
    assert [paper.doi for paper in list_papers(db_path, "new")] == ["10.1000/library"]
    assert "Archive paper" not in client.get("/").text

    single = client.post(
        "/journals/export",
        data={"journal_id": str(example), "issues": "1"},
        follow_redirects=False,
    )
    assert single.headers["content-disposition"] == 'attachment; filename="example-journal-abstracts.md"'
    assert "### [Fresh paper](https://doi.org/10.1000/new-issue)" in single.text
    assert "Archive paper" not in single.text
    assert "Beta paper" not in single.text


def test_export_abstracts_empty_and_busy(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, search=_search, fetch=_fetch, fetch_issues=lambda *args, **kwargs: [])
    db_path = tmp_path / "library.sqlite"
    journal_id = subscribe_journal(
        db_path,
        title="Example Journal",
        issns=("1234-5678",),
        publisher="",
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    empty = client.post(
        "/journals/export",
        data={"journal_id": str(journal_id), "issues": "4"},
        follow_redirects=False,
    )
    assert empty.status_code == 303
    assert empty.headers["location"] == "/journals?notice=export_empty"
    assert "No recent issues were found for those journals." in client.get(empty.headers["location"]).text

    app.state.lock.acquire()
    try:
        during_refresh = client.post(
            "/journals/export",
            data={"journal_id": str(journal_id), "issues": "4"},
            follow_redirects=False,
        )
    finally:
        app.state.lock.release()
    assert during_refresh.headers["location"] == "/journals?notice=export_empty"

    app.state.export_lock.acquire()
    try:
        busy = client.post(
            "/journals/export",
            data={"journal_id": str(journal_id), "issues": "4"},
            follow_redirects=False,
        )
    finally:
        app.state.export_lock.release()
    assert busy.headers["location"] == "/journals?notice=export_busy"
    assert "An export is already running." in client.get(busy.headers["location"]).text

    none = client.get("/journals")
    client.post(f"/journals/{journal_id}/unsubscribe", follow_redirects=False)
    after = client.get("/journals")
    assert "Export abstracts" in none.text
    assert "Export abstracts" not in after.text
    assert "No journals yet." in after.text


def _hit(
    doi: str,
    title: str,
    published: str,
    authors: str,
    abstract: str,
    volume: str | None = None,
    issue: str | None = None,
    issue_date: str | None = None,
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
        issue_date=issue_date,
    )


def _catalog_search(query, *, mailto=None, client=None):
    catalog = {
        "example": [
            JournalHit(
                title="Example Journal",
                issns=("1234-5678",),
                publisher="Example Press",
            )
        ],
        "other": [
            JournalHit(
                title="Other Journal",
                issns=("9999-999X",),
                publisher="Other Press",
            )
        ],
    }
    return catalog[query]


def _search(query, *, mailto=None, client=None):
    assert query == "example"
    return [
        JournalHit(
            title="Example Journal",
            issns=("1234-5678",),
            publisher="Example Press",
        )
    ]


def _fetch(issns, start, *, mailto=None, client=None, pause=None):
    assert issns == ("1234-5678",)
    return [
        PaperHit(
            doi="10.1000/example",
            title="A real paper",
            authors="Ada Lovelace",
            abstract="Hello from the abstract",
            published_date="2026-09-01",
            url="https://doi.org/10.1000/example",
        )
    ]


def test_update_runs_in_background(tmp_path):
    from fastapi.testclient import TestClient

    started = threading.Event()
    release = threading.Event()

    def fetch(issns, start, *, mailto=None, client=None, pause=None):
        started.set()
        release.wait(timeout=3)
        return _fetch(issns, start)

    app = create_app(tmp_path, search=_search, fetch=fetch)
    subscribe_journal(
        tmp_path / "library.sqlite",
        title="Example Journal",
        issns=("1234-5678",),
        publisher="",
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/refresh/status").json() == {"refreshing": False}

    started_at = time.monotonic()
    first = client.post("/refresh", follow_redirects=False)
    assert time.monotonic() - started_at < 1
    assert first.status_code == 303
    assert first.headers["location"] == "/"
    assert started.wait(timeout=2)
    assert client.get("/refresh/status").json() == {"refreshing": True}

    page = client.get("/")
    assert "Fetching papers" in page.text
    assert "Updating…" in page.text
    assert "/static/refresh.js" in page.text

    second = client.post("/refresh", follow_redirects=False)
    assert second.headers["location"] == "/?busy=1"

    release.set()
    app.state.refresh_thread.join(timeout=5)
    assert client.get("/refresh/status").json() == {"refreshing": False}
    done = client.get("/")
    assert "1 new paper from 1 journal." in done.text
    assert "A real paper" in done.text
    assert "/static/refresh.js" not in done.text
    assert "1 new paper from 1 journal." not in client.get("/").text


def test_bulk_status_moves_selected_papers(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    db_path = tmp_path / "library.sqlite"
    journal_id = subscribe_journal(db_path, title="Example Journal", issns=("1234-5678",), publisher="")
    upsert_papers(
        db_path,
        journal_id,
        "Example Journal",
        [
            PaperHit(
                doi=f"10.1000/bulk{n}",
                title=f"Bulk paper {n}",
                authors="",
                abstract=None,
                published_date="2026-09-01",
                url=f"https://doi.org/10.1000/bulk{n}",
            )
            for n in range(3)
        ],
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    inbox = client.get("/")
    assert 'id="bulk-form"' in inbox.text
    assert inbox.text.count('form="bulk-form"') == 3
    assert "Remove selected" not in inbox.text
    assert 'value="new"' not in inbox.text
    assert inbox.text.count('class="status-group"') == 8
    assert inbox.text.index('value="dismissed"') < inbox.text.index('value="reading"')
    assert inbox.text.index('value="reading"') < inbox.text.index('value="done"')
    reading_tab = client.get("/reading")
    assert 'value="reading"' not in reading_tab.text

    moved = client.post(
        "/papers/status/bulk",
        data={"status": "dismissed", "doi": ["10.1000/BULK0", "10.1000/bulk1"], "next": "/"},
        follow_redirects=False,
    )
    assert moved.status_code == 303
    assert moved.headers["location"] == "/"
    assert [paper.doi for paper in list_papers(db_path, "new")] == ["10.1000/bulk2"]
    assert len(list_papers(db_path, "dismissed")) == 2

    blocked = client.post(
        "/papers/status/bulk",
        data={"status": "removed", "doi": ["10.1000/bulk0", "10.1000/bulk2"], "next": "/"},
    )
    assert blocked.status_code == 400
    assert len(list_papers(db_path, "dismissed")) == 2

    assert "Remove selected" in client.get("/dismissed").text
    removed = client.post(
        "/papers/status/bulk",
        data={"status": "removed", "doi": ["10.1000/bulk0", "10.1000/bulk1"], "next": "/dismissed"},
        follow_redirects=False,
    )
    assert removed.headers["location"] == "/dismissed"
    assert len(list_papers(db_path, "removed")) == 2

    nothing = client.post("/papers/status/bulk", data={"status": "done", "next": "/"}, follow_redirects=False)
    assert nothing.status_code == 303
    unknown = client.post("/papers/status/bulk", data={"status": "archived", "doi": "10.1000/bulk2"})
    assert unknown.status_code == 400
    offsite = client.post(
        "/papers/status/bulk",
        data={"status": "done", "doi": "10.1000/bulk2", "next": "https://example.com"},
        follow_redirects=False,
    )
    assert offsite.headers["location"] == "/"
    assert [paper.doi for paper in list_papers(db_path, "done")] == ["10.1000/bulk2"]


def test_settings_chooses_the_folder_for_the_next_launch(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from paper_cart.config import data_dir_from_env, data_dir_preference_path
    from paper_cart.db import list_journals, subscribe_journal

    monkeypatch.delenv("PAPER_CART_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("paper_cart.config.default_data_dir", lambda: tmp_path / "user")
    current = tmp_path / "current"
    chosen = tmp_path / "chosen"
    app = create_app(current, search=_search, fetch=_fetch)
    subscribe_journal(
        app.state.db_path,
        title="Kept Journal",
        issns=("1111-1111",),
        publisher="",
    )
    (current / "marker.txt").write_text("keep", encoding="utf-8")
    before = app.state.db_path.read_bytes()
    client = TestClient(app, base_url="http://127.0.0.1")

    home = client.get("/")
    assert home.status_code == 200
    assert 'href="/settings"' in home.text

    page = client.get("/settings")
    assert page.status_code == 200
    assert f'data-current-folder>{current.resolve()}<' in page.text.replace("\n", "")
    assert "data-pending-folder" not in page.text
    assert 'name="data_dir"' in page.text

    saved = client.post("/settings", data={"data_dir": str(chosen)}, follow_redirects=False)
    assert saved.status_code == 303
    assert saved.headers["location"] == "/settings?saved=1"
    assert app.state.db_path.read_bytes() == before
    assert not (chosen / "library.sqlite").exists()
    assert not (chosen / "marker.txt").exists()
    assert (current / "marker.txt").read_text(encoding="utf-8") == "keep"
    assert data_dir_preference_path().read_text(encoding="utf-8") == f"{chosen.resolve()}\n"

    shown = client.get("/settings?saved=1")
    assert shown.status_code == 200
    assert f'data-current-folder>{current.resolve()}<' in shown.text.replace("\n", "")
    assert f'data-pending-folder>{chosen.resolve()}<' in shown.text.replace("\n", "")
    assert "Quit and start again to use the saved folder." in shown.text
    assert data_dir_from_env() == chosen.resolve()

    fresh = create_app(data_dir_from_env())
    assert list_journals(fresh.state.db_path) == []
    assert app.state.db_path.read_bytes() == before
    assert [journal.title for journal in list_journals(app.state.db_path)] == ["Kept Journal"]
    before = app.state.db_path.read_bytes()

    blocked = tmp_path / "not-a-folder"
    blocked.write_text("leave", encoding="utf-8")
    rejected = client.post("/settings", data={"data_dir": str(blocked)})
    assert rejected.status_code == 200
    assert "Choose a folder." in rejected.text
    assert data_dir_preference_path().read_text(encoding="utf-8") == f"{chosen.resolve()}\n"
    assert blocked.read_text(encoding="utf-8") == "leave"
    assert app.state.db_path.read_bytes() == before

    relative = client.post("/settings", data={"data_dir": "library"})
    assert "Enter a full folder path." in relative.text
    assert app.state.db_path.read_bytes() == before


def test_settings_keeps_a_library_already_in_the_chosen_folder(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from paper_cart.config import data_dir_from_env
    from paper_cart.db import init_db, list_journals, subscribe_journal

    monkeypatch.delenv("PAPER_CART_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("paper_cart.config.default_data_dir", lambda: tmp_path / "user")
    current = tmp_path / "current"
    chosen = tmp_path / "chosen"
    app = create_app(current, search=_search, fetch=_fetch)
    subscribe_journal(
        app.state.db_path,
        title="Kept Journal",
        issns=("1111-1111",),
        publisher="",
    )
    init_db(chosen / "library.sqlite")
    subscribe_journal(
        chosen / "library.sqlite",
        title="Other Journal",
        issns=("2222-2222",),
        publisher="",
    )
    before_current = app.state.db_path.read_bytes()
    before_chosen = (chosen / "library.sqlite").read_bytes()
    client = TestClient(app, base_url="http://127.0.0.1")
    saved = client.post(
        "/settings",
        data={"data_dir": str(chosen)},
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "Quit and start again to use the saved folder." in saved.text
    assert app.state.db_path.read_bytes() == before_current
    assert (chosen / "library.sqlite").read_bytes() == before_chosen

    opened = create_app(data_dir_from_env())
    assert [journal.title for journal in list_journals(opened.state.db_path)] == ["Other Journal"]
    assert app.state.db_path.read_bytes() == before_current


def test_settings_names_a_startup_override(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr("paper_cart.config.default_data_dir", lambda: tmp_path / "user")
    app = create_app(tmp_path, search=_search, fetch=_fetch)
    app.state.data_dir_source = "env"
    page = TestClient(app, base_url="http://127.0.0.1").get("/settings")
    assert "This session was started with PAPER_CART_DATA." in page.text
    assert f'data-current-folder>{tmp_path.resolve()}<' in page.text.replace("\n", "")


def test_health_and_quit(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/healthz").json() == {"app": "paper-cart"}
    assert 'action="/quit"' not in client.get("/").text
    assert client.post("/quit").status_code == 404

    stopped = threading.Event()
    app.state.shutdown = stopped.set
    assert 'action="/quit"' in client.get("/").text
    page = client.post("/quit")
    assert page.status_code == 200
    assert "Paper Cart has stopped" in page.text
    assert stopped.wait(timeout=3)


def test_settings_lists_library_files_and_exports_the_active_one(tmp_path):
    import sqlite3

    from fastapi.testclient import TestClient

    from paper_cart.db import get_setting, init_db, set_setting

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    set_setting(app.state.db_path, "shelf", "active")
    init_db(tmp_path / "notes.sqlite")
    set_setting(tmp_path / "notes.sqlite", "shelf", "other")
    other_before = (tmp_path / "notes.sqlite").read_bytes()
    client = TestClient(app, base_url="http://127.0.0.1")

    page = client.get("/settings")
    assert page.status_code == 200
    assert 'data-library-list' in page.text
    assert 'data-library="library.sqlite"' in page.text
    assert 'data-library="notes.sqlite"' in page.text
    assert 'data-library-active' in page.text
    assert "These changes happen now." in page.text
    assert "No restart is needed." not in page.text
    assert 'href="/settings/libraries/export"' in page.text
    assert 'action="/settings/libraries/import"' in page.text
    assert "Rename" in page.text

    exported = client.get("/settings/libraries/export")
    assert exported.status_code == 200
    disposition = exported.headers["content-disposition"]
    assert "library.sqlite" in disposition
    copy = tmp_path / "downloaded.sqlite"
    copy.write_bytes(exported.content)
    connection = sqlite3.connect(copy)
    try:
        row = connection.execute("SELECT value FROM settings WHERE key = 'shelf'").fetchone()
    finally:
        connection.close()
    assert row[0] == "active"
    assert (tmp_path / "notes.sqlite").read_bytes() == other_before
    assert get_setting(tmp_path / "notes.sqlite", "shelf", "") == "other"


def test_settings_switches_and_renames_without_touching_other_files(tmp_path):
    from fastapi.testclient import TestClient

    from paper_cart.db import get_setting, init_db, list_journals, set_setting, subscribe_journal

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    subscribe_journal(app.state.db_path, title="Shelf One", issns=("1000-0001",), publisher="")
    init_db(tmp_path / "notes.sqlite")
    subscribe_journal(
        tmp_path / "notes.sqlite",
        title="Shelf Two",
        issns=("1000-0002",),
        publisher="",
    )
    active_before = app.state.db_path.read_bytes()
    client = TestClient(app, base_url="http://127.0.0.1")

    switched = client.post(
        "/settings/libraries/active",
        data={"library": "notes.sqlite"},
        follow_redirects=False,
    )
    assert switched.status_code == 303
    assert switched.headers["location"] == "/settings?switched=1"
    assert app.state.db_path.name == "notes.sqlite"
    assert (tmp_path / "library.sqlite").read_bytes() == active_before
    assert (tmp_path / "active-library").read_text(encoding="utf-8").strip() == "notes.sqlite"
    shown = client.get("/settings?switched=1")
    assert "This session is using notes.sqlite." in shown.text
    assert 'data-library="notes.sqlite" data-library-active' in shown.text
    journals = client.get("/journals")
    assert "Shelf Two" in journals.text
    assert "Shelf One" not in journals.text

    fresh = create_app(tmp_path, search=_search, fetch=_fetch)
    assert fresh.state.db_path.name == "notes.sqlite"
    assert [journal.title for journal in list_journals(fresh.state.db_path)] == ["Shelf Two"]

    renamed = client.post(
        "/settings/libraries/rename",
        data={"library": "notes.sqlite", "name": "archive"},
        follow_redirects=False,
    )
    assert renamed.status_code == 303
    assert app.state.db_path.name == "archive.sqlite"
    assert (tmp_path / "library.sqlite").read_bytes() == active_before
    assert not (tmp_path / "notes.sqlite").exists()
    assert (tmp_path / "active-library").read_text(encoding="utf-8").strip() == "archive.sqlite"
    assert get_setting(app.state.db_path, "shelf", "missing") == "missing"
    again = create_app(tmp_path, search=_search, fetch=_fetch)
    assert again.state.db_path.name == "archive.sqlite"
    assert "Shelf Two" in TestClient(again, base_url="http://127.0.0.1").get("/journals").text

    empty = client.post(
        "/settings/libraries/rename",
        data={"library": "archive.sqlite", "name": "   "},
    )
    assert empty.status_code == 200
    assert "Enter a library name." in empty.text
    clash = client.post(
        "/settings/libraries/rename",
        data={"library": "archive.sqlite", "name": "library.sqlite"},
    )
    assert clash.status_code == 200
    assert "already has that name" in clash.text
    assert (tmp_path / "library.sqlite").read_bytes() == active_before
    assert app.state.db_path.name == "archive.sqlite"

    archive_before = (tmp_path / "archive.sqlite").read_bytes()
    parked = client.post(
        "/settings/libraries/rename",
        data={"library": "library.sqlite", "name": "spare"},
        follow_redirects=False,
    )
    assert parked.status_code == 303
    assert (tmp_path / "spare.sqlite").read_bytes() == active_before
    assert (tmp_path / "archive.sqlite").read_bytes() == archive_before
    assert not (tmp_path / "library.sqlite").exists()
    assert app.state.db_path.name == "archive.sqlite"
    assert (tmp_path / "active-library").read_text(encoding="utf-8").strip() == "archive.sqlite"


def test_settings_import_validates_before_replacing_and_keeps_other_files(tmp_path):
    from fastapi.testclient import TestClient

    from paper_cart.db import init_db, subscribe_journal

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    subscribe_journal(app.state.db_path, title="Shelf One", issns=("1000-0001",), publisher="")
    init_db(tmp_path / "notes.sqlite")
    subscribe_journal(
        tmp_path / "notes.sqlite",
        title="Shelf Two",
        issns=("1000-0002",),
        publisher="",
    )
    other_before = (tmp_path / "notes.sqlite").read_bytes()
    active_before = app.state.db_path.read_bytes()
    client = TestClient(app, base_url="http://127.0.0.1")

    refused = client.post(
        "/settings/libraries/import",
        data={"name": "library.sqlite"},
        files={"upload": ("library.sqlite", other_before, "application/octet-stream")},
    )
    assert refused.status_code == 200
    assert "Confirm that you want to add or replace this library file." in refused.text
    assert app.state.db_path.read_bytes() == active_before
    assert (tmp_path / "notes.sqlite").read_bytes() == other_before

    garbage = client.post(
        "/settings/libraries/import",
        data={"name": "library.sqlite", "confirm": "yes"},
        files={"upload": ("library.sqlite", b"not a library", "application/octet-stream")},
    )
    assert garbage.status_code == 200
    assert "not a library" in garbage.text
    assert app.state.db_path.read_bytes() == active_before
    assert (tmp_path / "notes.sqlite").read_bytes() == other_before
    assert not list(tmp_path.glob(".import-*.partial"))
    assert not list(tmp_path.glob(".*.previous"))

    added = client.post(
        "/settings/libraries/import",
        data={"name": "extra.sqlite", "confirm": "yes"},
        files={"upload": ("extra.sqlite", other_before, "application/octet-stream")},
        follow_redirects=False,
    )
    assert added.status_code == 303
    assert added.headers["location"] == "/settings?imported=1"
    assert app.state.db_path.name == "library.sqlite"
    assert app.state.db_path.read_bytes() == active_before
    assert (tmp_path / "notes.sqlite").read_bytes() == other_before
    assert (tmp_path / "extra.sqlite").is_file()
    assert "Shelf One" in client.get("/journals").text

    replaced = client.post(
        "/settings/libraries/import",
        data={"name": "library.sqlite", "confirm": "yes"},
        files={"upload": ("library.sqlite", (tmp_path / "notes.sqlite").read_bytes(), "application/octet-stream")},
        follow_redirects=True,
    )
    assert replaced.status_code == 200
    assert "This session is using the imported file." in replaced.text
    assert (tmp_path / "notes.sqlite").read_bytes() == other_before
    assert (tmp_path / "extra.sqlite").is_file()
    assert not list(tmp_path.glob(".*.previous"))
    assert "Shelf Two" in client.get("/journals").text
    assert "Shelf One" not in client.get("/journals").text


def test_library_file_changes_wait_while_an_update_is_running(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    before = app.state.db_path.read_bytes()
    app.state.refresh_jobs = 1
    client = TestClient(app, base_url="http://127.0.0.1")
    page = client.post(
        "/settings/libraries/rename",
        data={"library": "library.sqlite", "name": "archive.sqlite"},
    )
    assert page.status_code == 200
    assert "An update is running." in page.text
    assert app.state.db_path.read_bytes() == before
    assert (tmp_path / "library.sqlite").is_file()
    assert not (tmp_path / "archive.sqlite").exists()


def test_cross_site_writes_are_blocked(tmp_path):
    from fastapi.testclient import TestClient

    from paper_cart.db import get_setting

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    client = TestClient(app, base_url="http://127.0.0.1")
    library_before = app.state.db_path.read_bytes()
    appearance = {
        "mode": "dark",
        "light": "alucard",
        "dark": "dracula",
        "font": "sans",
    }
    cross_site = {
        "Origin": "https://evil.example",
        "Sec-Fetch-Site": "cross-site",
    }

    blocked = client.post("/appearance", data=appearance, headers=cross_site)
    assert blocked.status_code == 403
    assert blocked.text == "Cross-site request blocked."
    assert get_setting(app.state.db_path, "theme_mode", "system") == "system"

    no_origin = client.post(
        "/appearance",
        data=appearance,
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert no_origin.status_code == 403
    assert get_setting(app.state.db_path, "theme_mode", "system") == "system"

    folder = tmp_path / "created-by-cross-site" / "deep"
    settings = client.post(
        "/settings",
        data={"data_dir": str(folder)},
        headers=cross_site,
    )
    assert settings.status_code == 403
    assert not folder.exists()

    imported = client.post(
        "/settings/libraries/import",
        data={"name": "library.sqlite", "confirm": "yes"},
        files={"upload": ("library.sqlite", b"not a library", "application/octet-stream")},
        headers=cross_site,
    )
    assert imported.status_code == 403
    assert app.state.db_path.read_bytes() == library_before

    assert client.post("/quit", headers=cross_site).status_code == 403

    browser = TestClient(app, base_url="http://127.0.0.1:8000")
    allowed = browser.post(
        "/appearance",
        data=appearance,
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert allowed.status_code == 204
    assert get_setting(app.state.db_path, "theme_mode", "system") == "dark"

    for site in ("same-origin", "none"):
        kept = client.post(
            "/appearance",
            data={"mode": "light", "light": "alucard", "dark": "dracula", "font": "serif"},
            headers={"Sec-Fetch-Site": site},
        )
        assert kept.status_code == 204

    opened = client.get("/healthz", headers=cross_site)
    assert opened.status_code == 200
    assert opened.json() == {"app": "paper-cart"}


def test_only_loopback_hosts_are_accepted(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, search=_search, fetch=_fetch)
    library_before = app.state.db_path.read_bytes()
    rebind = TestClient(app, base_url="http://rebind.evil.example:8000")

    for path in ("/settings", "/settings/libraries/export", "/healthz"):
        rejected = rebind.get(path)
        assert rejected.status_code == 400
        assert b"SQLite format 3" not in rejected.content

    folder = tmp_path / "created-by-cross-site" / "deep"
    written = rebind.post(
        "/settings",
        data={"data_dir": str(folder)},
        headers={"Origin": "http://rebind.evil.example:8000"},
    )
    assert written.status_code == 400
    assert not folder.exists()
    assert app.state.db_path.read_bytes() == library_before

    local = TestClient(app, base_url="http://localhost")
    assert local.get("/healthz").status_code == 200
    assert local.get("/settings").status_code == 200
    saved = local.post(
        "/appearance",
        data={"mode": "dark", "light": "alucard", "dark": "dracula", "font": "sans"},
        headers={"Origin": "http://localhost"},
    )
    assert saved.status_code == 204
