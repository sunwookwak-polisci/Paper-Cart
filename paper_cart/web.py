"""Localhost pages for journals and reading progress."""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from paper_cart.config import (
    ConfigError,
    load_contact_email,
    read_saved_data_dir,
    resolve_data_dir,
    save_data_dir_preference,
)
from paper_cart.crossref import (
    CrossrefError,
    fetch_papers as default_fetch,
    fetch_recent_issues as default_fetch_issues,
    normalize_issns,
    search_journals as default_search,
)
from paper_cart.export import (
    MAX_ISSUES,
    export_filename,
    export_journal_abstracts,
    format_abstract_export,
)
from paper_cart.db import (
    STATUSES,
    Journal,
    LibraryUnavailable,
    Paper,
    library_lock,
    add_cart_item,
    clear_cart,
    ensure_custom_order,
    get_journal,
    get_setting,
    init_db,
    list_cart,
    list_journals,
    list_journals_by_rank,
    list_papers,
    move_journal,
    remove_cart_item,
    set_journal_order,
    set_setting,
    set_status,
    set_statuses,
    status_counts,
    subscribe_journal,
    unsubscribe_journal,
)
from paper_cart.libraries import (
    BUSY_MESSAGE,
    MAX_LIBRARY_BYTES,
    LibraryBusy,
    LibraryFileError,
    activate_library_file,
    active_library_path,
    export_library_copy,
    import_target_name,
    install_library_file,
    list_library_names,
    recover_library_backups,
    rename_library_file,
    write_active_name,
)
from paper_cart.refresh import refresh_journals

APP_ID = "paper-cart"
PACKAGE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE / "templates"))

VIEWS = {
    "new": ("New", "Nothing new. Subscribe to a journal, then update to fetch recent papers."),
    "reading": ("Reading", "Nothing in progress."),
    "read_later": ("Read later", "Nothing saved for later."),
    "done": ("Done", "Nothing finished yet."),
    "dismissed": ("Dismissed", "Nothing dismissed."),
    "removed": ("Removed", "Nothing removed."),
}

NAV = (
    ("new", "/", "New"),
    ("reading", "/reading", "Reading"),
    ("read_later", "/later", "Read later"),
    ("done", "/done", "Done"),
    ("dismissed", "/dismissed", "Dismissed"),
    ("removed", "/removed", "Removed"),
)

STATUS_LABELS = (
    ("new", "New"),
    ("read_later", "Read later"),
    ("reading", "Reading"),
    ("done", "Done"),
    ("dismissed", "Dismiss"),
)


def create_app(
    data_dir: Path | None = None, *, search=None, fetch=None, fetch_issues=None
) -> FastAPI:
    if data_dir is None:
        folder, source = resolve_data_dir(None)
    else:
        folder, source = data_dir, "given"
    folder.mkdir(parents=True, exist_ok=True)
    recover_library_backups(folder)
    db_path = active_library_path(folder)
    init_db(db_path)

    app = FastAPI(title="Paper Cart")
    app.mount("/static", StaticFiles(directory=str(PACKAGE / "static")), name="static")
    app.state.data_dir = folder
    app.state.data_dir_source = source
    app.state.db_path = db_path
    app.state.library_hold = False
    app.state.lock = threading.Lock()
    app.state.export_lock = threading.Lock()
    app.state.last_report = None
    app.state.refreshing = False
    app.state.report_pending = False
    app.state.refresh_thread = None
    app.state.refresh_gate = threading.Lock()
    app.state.refresh_jobs = 0
    app.state.search_journals = search or default_search
    app.state.fetch_papers = fetch or default_fetch
    app.state.fetch_recent_issues = fetch_issues or default_fetch_issues
    app.state.shutdown = None

    @app.get("/")
    def inbox(request: Request):
        return _papers(request, "new")

    @app.get("/reading")
    def reading(request: Request):
        return _papers(request, "reading")

    @app.get("/later")
    def later(request: Request):
        return _papers(request, "read_later")

    @app.get("/done")
    def done(request: Request):
        return _papers(request, "done")

    @app.get("/dismissed")
    def dismissed(request: Request):
        return _papers(request, "dismissed")

    @app.get("/removed")
    def removed(request: Request):
        return _papers(request, "removed")

    @app.get("/journals")
    def journals(request: Request, q: str = ""):
        query = q.strip()
        results = []
        error = _config_error(request)
        known = _known_issns(request)
        cart = list_cart(request.app.state.db_path)
        cart_issns = {issn for item in cart for issn in item.issns}
        if error is None and len(query) >= 2:
            try:
                hits = request.app.state.search_journals(query, mailto=_mailto(request))
            except CrossrefError as exc:
                error = str(exc)
            else:
                results = [
                    {
                        "title": hit.title,
                        "publisher": hit.publisher,
                        "issns": hit.issns,
                        "issns_csv": ",".join(hit.issns),
                        "subscribed": any(issn in known for issn in hit.issns),
                        "in_cart": any(issn in cart_issns for issn in hit.issns),
                    }
                    for hit in hits
                ]
        elif query and error is None:
            error = "Type at least two characters."
        notice = _NOTICE.get(request.query_params.get("notice", ""), "")
        subscribed_raw = request.query_params.get("subscribed", "")
        subscribed_count = int(subscribed_raw) if subscribed_raw.isdigit() else 0
        return templates.TemplateResponse(
            request,
            "journals.html",
            _page_context(
                request,
                heading="Journals",
                active="journals",
                query=query,
                results=results,
                error=error,
                notice=notice,
                subscribed_count=subscribed_count,
                selectable=any(
                    not result["subscribed"] and not result["in_cart"] for result in results
                ),
                cart=cart,
                journals=list_journals(request.app.state.db_path, subscribed_only=True),
                max_issues=MAX_ISSUES,
            ),
        )

    @app.post("/journals/cart")
    def add_to_cart(
        request: Request,
        q: str = Form(""),
        pick: list[int] | None = Form(default=None),
        title: list[str] | None = Form(default=None),
        publisher: list[str] | None = Form(default=None),
        issns: list[str] | None = Form(default=None),
    ):
        if not pick:
            return RedirectResponse(_journals_location(q, notice="select"), status_code=303)
        titles = title or []
        publishers = publisher or []
        issn_values = issns or []
        added = False
        for index in pick:
            if index < 0 or index >= len(titles) or index >= len(issn_values):
                continue
            parsed = normalize_issns(issn_values[index].split(","))
            cleaned_title = titles[index].strip()
            if not parsed or not cleaned_title:
                continue
            journal_publisher = publishers[index].strip() if index < len(publishers) else ""
            add_cart_item(
                request.app.state.db_path,
                title=cleaned_title,
                issns=parsed,
                publisher=journal_publisher,
            )
            added = True
        if not added:
            return RedirectResponse(_journals_location(q, notice="select"), status_code=303)
        return RedirectResponse(_journals_location(q), status_code=303)

    @app.post("/journals/cart/remove")
    def remove_from_cart(request: Request, item_id: int = Form(...), q: str = Form("")):
        remove_cart_item(request.app.state.db_path, item_id)
        return RedirectResponse(_journals_location(q), status_code=303)

    @app.post("/journals/checkout")
    def checkout(request: Request):
        state = request.app.state
        journals: list[Journal] = []
        for item in list_cart(state.db_path):
            journal_id = subscribe_journal(
                state.db_path,
                title=item.title,
                issns=item.issns,
                publisher=item.publisher,
            )
            journal = get_journal(state.db_path, journal_id)
            if journal is not None:
                journals.append(journal)
        clear_cart(state.db_path)
        if journals:
            start_checkout_refresh(request.app, journals)
        location = _journals_location(subscribed=str(len(journals))) if journals else "/journals"
        return RedirectResponse(location, status_code=303)

    @app.post("/journals/export")
    def export_abstracts(
        request: Request,
        journal_id: list[int] | None = Form(default=None),
        issues: str = Form("4"),
    ):
        selected_ids = journal_id or []
        subscribed = {
            journal.id: journal
            for journal in list_journals(request.app.state.db_path, subscribed_only=True)
        }
        journals = [subscribed[item] for item in selected_ids if item in subscribed]
        if not journals:
            return RedirectResponse(
                _journals_location(notice="select_export"),
                status_code=303,
            )
        try:
            issue_count = int(issues.strip())
        except ValueError:
            issue_count = 0
        if issue_count < 1 or issue_count > MAX_ISSUES:
            return RedirectResponse(_journals_location(notice="issues"), status_code=303)
        config_error = _config_error(request)
        if config_error:
            return RedirectResponse(
                _journals_location(notice="export_config"),
                status_code=303,
            )
        state = request.app.state
        if not state.export_lock.acquire(blocking=False):
            return RedirectResponse(_journals_location(notice="export_busy"), status_code=303)
        try:
            exports = export_journal_abstracts(
                journals,
                issue_count,
                fetch=state.fetch_recent_issues,
                mailto=_mailto(request),
            )
        finally:
            state.export_lock.release()
        text = format_abstract_export(exports)
        if not text:
            return RedirectResponse(
                _journals_location(notice="export_empty"),
                status_code=303,
            )
        filename = export_filename(journals)
        return Response(
            content=text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/journals/{journal_id}/unsubscribe")
    def unsubscribe(journal_id: int, request: Request):
        unsubscribe_journal(request.app.state.db_path, journal_id)
        return RedirectResponse("/journals", status_code=303)

    @app.post("/refresh")
    def refresh(request: Request):
        if not start_refresh(request.app):
            return RedirectResponse("/?busy=1", status_code=303)
        return RedirectResponse("/", status_code=303)

    @app.get("/refresh/status")
    def refresh_status(request: Request):
        return {"refreshing": bool(request.app.state.refreshing)}

    @app.post("/view")
    def update_view(
        request: Request,
        next: str = Form("/"),
        group: str = Form(""),
        group_sort: str = Form(""),
        order_open: str = Form(""),
    ):
        db_path = request.app.state.db_path
        if group in {"0", "1"}:
            set_setting(db_path, "group_by_journal", group)
        if group_sort in {"date", "alpha", "custom"}:
            set_setting(db_path, "group_sort", group_sort)
            if group_sort == "custom":
                ensure_custom_order(db_path)
        if order_open in {"0", "1"}:
            set_setting(db_path, "order_open", order_open)
        return RedirectResponse(safe_next(next), status_code=303)

    @app.post("/journals/order")
    def reorder_journal(
        request: Request,
        next: str = Form("/"),
        journal_id: str = Form(""),
        direction: str = Form(""),
        order: list[str] = Form(default_factory=list),
    ):
        db_path = request.app.state.db_path
        ranked = [int(value) for value in order if value.isdigit()]
        if ranked:
            set_journal_order(db_path, ranked)
        elif journal_id.isdigit() and direction in {"up", "down"}:
            move_journal(db_path, int(journal_id), -1 if direction == "up" else 1)
        return RedirectResponse(safe_next(next), status_code=303)

    @app.post("/papers/status")
    def update_status(
        request: Request,
        doi: str = Form(...),
        status: str = Form(...),
        next: str = Form("/"),
    ):
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status.")
        try:
            updated = set_status(request.app.state.db_path, doi.strip().lower(), status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Paper not found.")
        return RedirectResponse(safe_next(next), status_code=303)

    @app.get("/settings")
    def settings_page(request: Request):
        return templates.TemplateResponse(request, "settings.html", _settings_view(request))

    @app.post("/settings")
    def save_settings(request: Request, data_dir: str = Form("")):
        try:
            save_data_dir_preference(data_dir)
        except ConfigError as exc:
            return templates.TemplateResponse(
                request,
                "settings.html",
                _settings_view(request, error=str(exc), form_folder=data_dir),
            )
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.get("/settings/libraries/export")
    def export_library(request: Request):
        try:
            copy = export_library_copy(request.app.state.db_path)
        except ConfigError as exc:
            return _settings_error(request, str(exc))
        return FileResponse(
            copy,
            media_type="application/octet-stream",
            filename=request.app.state.db_path.name,
            background=BackgroundTask(copy.unlink, missing_ok=True),
        )

    @app.post("/settings/libraries/active")
    def use_library(request: Request, library: str = Form("")):
        try:
            with _library_mutation(request.app):
                path = activate_library_file(request.app.state.data_dir, library)
                request.app.state.db_path = path
        except LibraryBusy:
            return _settings_error(request, BUSY_MESSAGE)
        except ConfigError as exc:
            return _settings_error(request, str(exc))
        return RedirectResponse("/settings?switched=1", status_code=303)

    @app.post("/settings/libraries/rename")
    def rename_library(request: Request, library: str = Form(""), name: str = Form("")):
        folder = request.app.state.data_dir
        renamed = library
        try:
            with _library_mutation(request.app):
                was_active = _same_library(request.app.state.db_path, folder / library)
                renamed = rename_library_file(folder, library, name)
                if was_active and renamed != library:
                    try:
                        write_active_name(folder, renamed)
                    except OSError as exc:
                        rename_library_file(folder, renamed, library)
                        raise LibraryFileError("That library could not be renamed.") from exc
                    request.app.state.db_path = folder / renamed
        except LibraryBusy:
            return _settings_error(request, BUSY_MESSAGE)
        except ConfigError as exc:
            return _settings_error(request, str(exc))
        if renamed == library:
            return RedirectResponse("/settings?renamed=1&same=1", status_code=303)
        return RedirectResponse("/settings?renamed=1", status_code=303)

    @app.post("/settings/libraries/import")
    def import_library(
        request: Request,
        upload: UploadFile = File(...),
        name: str = Form(""),
        confirm: str = Form(""),
    ):
        folder = request.app.state.data_dir
        if confirm != "yes":
            return _settings_error(
                request,
                "Confirm that you want to add or replace this library file.",
                import_name=name,
            )
        temporary = None
        replaced_active = False
        existed = False
        try:
            temporary = _store_upload(folder, upload)
            target_name = import_target_name(folder, name, upload.filename)
            existed = (folder / target_name).is_file()
            with _library_mutation(request.app):
                was_active = _same_library(request.app.state.db_path, folder / target_name)
                installed = install_library_file(folder, target_name, temporary)
                temporary = None
                init_db(folder / installed)
                if was_active:
                    request.app.state.db_path = folder / installed
                    replaced_active = True
        except LibraryBusy:
            return _settings_error(request, BUSY_MESSAGE, import_name=name)
        except ConfigError as exc:
            return _settings_error(request, str(exc), import_name=name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        if replaced_active:
            return RedirectResponse("/settings?imported=1&active=1", status_code=303)
        if existed:
            return RedirectResponse("/settings?imported=1&replaced=1", status_code=303)
        return RedirectResponse("/settings?imported=1", status_code=303)

    @app.get("/healthz")
    def healthz():
        return {"app": APP_ID}

    @app.post("/appearance")
    def save_appearance(
        request: Request,
        mode: str = Form("system"),
        light: str = Form("alucard"),
        dark: str = Form("dracula"),
        font: str = Form("serif"),
    ):
        saved = _normalize_appearance(mode, light, dark, font)
        try:
            set_setting(request.app.state.db_path, "theme_mode", saved["theme_mode"])
            set_setting(request.app.state.db_path, "theme_light", saved["theme_light"])
            set_setting(request.app.state.db_path, "theme_dark", saved["theme_dark"])
            set_setting(request.app.state.db_path, "theme_font", saved["theme_font"])
        except LibraryUnavailable as exc:
            raise HTTPException(status_code=404, detail="The library is not available.") from exc
        return Response(status_code=204)

    @app.post("/quit")
    def quit_app(request: Request):
        shutdown = request.app.state.shutdown
        if shutdown is None:
            raise HTTPException(status_code=404, detail="Quit is not available.")
        threading.Timer(1.0, shutdown).start()
        return templates.TemplateResponse(request, "quit.html", {"heading": "Stopped"})

    @app.post("/papers/status/bulk")
    def update_statuses(
        request: Request,
        status: str = Form(...),
        doi: list[str] = Form(default_factory=list),
        next: str = Form("/"),
    ):
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status.")
        dois = [value.strip().lower() for value in doi if value.strip()]
        try:
            set_statuses(request.app.state.db_path, dois, status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(safe_next(next), status_code=303)

    @app.exception_handler(LibraryUnavailable)
    def library_unavailable(request: Request, exc: LibraryUnavailable):
        if request.url.path.startswith("/settings"):
            return _settings_error(
                request,
                "Choose a library file below.",
            )
        return RedirectResponse("/settings?unavailable=1", status_code=303)

    return app


def start_checkout_refresh(app: FastAPI, journals: list[Journal]) -> None:
    if not _begin_refresh(app):
        return
    _run_refresh(app, journals, name="paper-cart-checkout")


def start_startup_refresh(app: FastAPI) -> None:
    if list_journals(app.state.db_path, subscribed_only=True):
        start_refresh(app)


def start_refresh(app: FastAPI) -> bool:
    """Check every subscribed journal in the background.

    Returns False when another update is already running.
    """
    with app.state.refresh_gate:
        if app.state.refresh_jobs or app.state.library_hold:
            return False
        app.state.refresh_jobs += 1
        app.state.refreshing = True
    _run_refresh(app, None, name="paper-cart-refresh")
    return True


def _run_refresh(app: FastAPI, journals: list[Journal] | None, *, name: str) -> None:
    """Run one counted refresh job; the caller has already counted it."""

    def run() -> None:
        try:
            with app.state.lock:
                try:
                    mailto = load_contact_email(app.state.data_dir / "config.toml")
                except ConfigError as exc:
                    app.state.last_report = _report_error(str(exc))
                else:
                    app.state.last_report = refresh_journals(
                        app.state.db_path,
                        journals
                        if journals is not None
                        else list_journals(app.state.db_path, subscribed_only=True),
                        fetch=app.state.fetch_papers,
                        mailto=mailto,
                    )
                app.state.report_pending = True
        finally:
            _end_refresh(app)

    thread = threading.Thread(target=run, name=name, daemon=True)
    app.state.refresh_thread = thread
    thread.start()


def safe_next(value: str, default: str = "/") -> str:
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return default


def _papers(request: Request, status: str):
    heading, empty = VIEWS[status]
    db_path = request.app.state.db_path
    query = request.query_params.get("q", "").strip()
    grouped = get_setting(db_path, "group_by_journal", "0") == "1"
    group_sort = get_setting(db_path, "group_sort", "date")
    if group_sort not in {"date", "alpha", "custom"}:
        group_sort = "date"
    papers = list_papers(db_path, status, query=query)
    order_journals = list_journals_by_rank(db_path) if grouped else []
    refreshing = bool(request.app.state.refreshing)
    show_report = request.query_params.get("updated") == "1"
    if request.app.state.report_pending and not refreshing:
        show_report = True
        request.app.state.report_pending = False
    return templates.TemplateResponse(
        request,
        "papers.html",
        _page_context(
            request,
            heading=heading,
            active=status,
            papers=papers,
            groups=_order_groups(papers, group_sort, order_journals) if grouped else [],
            grouped=grouped,
            group_sort=group_sort,
            order_journals=order_journals if group_sort == "custom" else [],
            order_open=get_setting(db_path, "order_open", "1") == "1",
            query=query,
            list_path=_list_path(request.url.path, query),
            empty=empty,
            show_report=show_report,
            busy=request.query_params.get("busy") == "1",
        ),
    )


@contextmanager
def _library_mutation(app: FastAPI):
    """Block a new update and keep every library connection closed for a swap."""
    with app.state.refresh_gate:
        if app.state.refresh_jobs or app.state.library_hold:
            raise LibraryBusy()
        app.state.library_hold = True
    try:
        with library_lock():
            yield
    finally:
        with app.state.refresh_gate:
            app.state.library_hold = False


def _settings_error(request: Request, message: str, import_name: str = ""):
    return templates.TemplateResponse(
        request,
        "settings.html",
        _settings_view(request, error=message, import_name=import_name),
    )


def _same_library(current: Path, candidate: Path) -> bool:
    if not candidate.is_file():
        return False
    if current.name == candidate.name and current.parent == candidate.parent:
        return True
    try:
        return current.resolve() == candidate.resolve()
    except OSError:
        return False


def _store_upload(folder: Path, upload: UploadFile) -> Path:
    path = folder / f".import-{uuid.uuid4().hex}.partial"
    size = 0
    try:
        with path.open("wb") as handle:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_LIBRARY_BYTES:
                    raise LibraryFileError("That library file is too large.")
                handle.write(chunk)
    except LibraryFileError:
        path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise LibraryFileError("That file could not be saved.") from exc
    if size == 0:
        path.unlink(missing_ok=True)
        raise LibraryFileError("Choose a library file.")
    return path


def _library_action_notice(request: Request, active_library: str) -> str:
    params = request.query_params
    if params.get("unavailable") == "1":
        return "This session is using the current file."
    if params.get("switched") == "1":
        return f"This session is using {active_library}."
    if params.get("renamed") == "1" and params.get("same") == "1":
        return "That file already has that name."
    if params.get("renamed") == "1":
        return "Renamed that file."
    if params.get("imported") == "1" and params.get("active") == "1":
        return "This session is using the imported file."
    if params.get("imported") == "1" and params.get("replaced") == "1":
        return "Replaced that file."
    if params.get("imported") == "1":
        return "Added that file."
    return ""


def _settings_view(
    request: Request,
    *,
    error: str = "",
    form_folder: str | None = None,
    import_name: str = "",
) -> dict:
    current = request.app.state.data_dir.expanduser().resolve()
    saved = read_saved_data_dir()
    pending: Path | None = None
    if saved is not None:
        try:
            saved_resolved = saved.expanduser().resolve()
        except OSError:
            saved_resolved = saved
        if saved_resolved != current:
            pending = saved_resolved
    if form_folder is None:
        form_folder = str(pending or current)
    source = getattr(request.app.state, "data_dir_source", "given")
    active_library = request.app.state.db_path.name
    libraries = list_library_names(request.app.state.data_dir)
    notice = ""
    if not error:
        notice = _library_action_notice(request, active_library)
    if request.query_params.get("saved") == "1" and not error and not notice:
        if pending is None:
            notice = "Saved."
        else:
            notice = "Quit and start again to use the saved folder."
    return _page_context(
        request,
        heading="Settings",
        active="settings",
        current_folder=str(current),
        pending_folder=str(pending) if pending else "",
        form_folder=form_folder,
        error=error,
        notice=notice,
        override_note=_OVERRIDE_NOTE.get(source, ""),
        libraries=libraries,
        active_library=active_library,
        import_name=import_name,
    )


_APPEARANCE_MODES = ("light", "dark", "system")
_APPEARANCE_LIGHTS = ("alucard", "tokyo-light", "ayu-light", "solarized-light")
_APPEARANCE_DARKS = ("dracula", "tokyo-night", "ayu-dark", "solarized-dark")
_APPEARANCE_FONTS = ("serif", "sans")


def _normalize_appearance(mode: str, light: str, dark: str, font: str) -> dict[str, str]:
    """Keep a saved theme inside the current choices.

    A stored Catppuccin palette falls back to Alucard or Dracula.
    """
    if light == "catppuccin-latte":
        light = "alucard"
    if dark == "catppuccin-mocha":
        dark = "dracula"
    if mode not in _APPEARANCE_MODES:
        mode = "system"
    if light not in _APPEARANCE_LIGHTS:
        light = "alucard"
    if dark not in _APPEARANCE_DARKS:
        dark = "dracula"
    if font not in _APPEARANCE_FONTS:
        font = "serif"
    theme_id = dark if mode == "dark" else light
    return {
        "theme_mode": mode,
        "theme_light": light,
        "theme_dark": dark,
        "theme_font": font,
        "theme_id": theme_id,
    }


def _appearance(db_path: Path) -> dict[str, str]:
    try:
        mode = get_setting(db_path, "theme_mode", "system")
        light = get_setting(db_path, "theme_light", "alucard")
        dark = get_setting(db_path, "theme_dark", "dracula")
        font = get_setting(db_path, "theme_font", "serif")
    except LibraryUnavailable:
        mode, light, dark, font = "system", "alucard", "dracula", "serif"
    return _normalize_appearance(mode, light, dark, font)


def _page_context(request: Request, **extra):
    try:
        counts = status_counts(request.app.state.db_path)
    except LibraryUnavailable:
        counts = {status: 0 for status in STATUSES}
    context = {
        "counts": counts,
        "nav": NAV,
        "status_labels": STATUS_LABELS,
        "current_path": request.url.path,
        "report": request.app.state.last_report,
        "refreshing": bool(request.app.state.refreshing),
        "can_quit": request.app.state.shutdown is not None,
    }
    context.update(_appearance(request.app.state.db_path))
    context.update(extra)
    return context


def _order_groups(
    papers: list[Paper],
    group_sort: str,
    journals: list[Journal],
) -> list[tuple[str, list[Paper]]]:
    grouped: dict[str, list[Paper]] = {}
    order: list[str] = []
    for paper in papers:
        if paper.journal_title not in grouped:
            grouped[paper.journal_title] = []
            order.append(paper.journal_title)
        grouped[paper.journal_title].append(paper)

    def latest(title: str) -> str | None:
        dates = [paper.published_date for paper in grouped[title] if paper.published_date]
        return max(dates) if dates else None

    def by_date(titles: list[str]) -> list[str]:
        titled = sorted(titles, key=lambda title: title.casefold())
        dated = [title for title in titled if latest(title)]
        undated = [title for title in titled if not latest(title)]
        dated.sort(key=lambda title: latest(title) or "", reverse=True)
        return dated + undated

    if group_sort == "alpha":
        order.sort(key=lambda title: title.casefold())
    elif group_sort == "custom":
        rank_by_title: dict[str, int | None] = {}
        for journal in journals:
            if journal.title not in rank_by_title or (
                rank_by_title[journal.title] is None and journal.sort_rank is not None
            ):
                rank_by_title[journal.title] = journal.sort_rank
        ranked = [title for title in order if rank_by_title.get(title) is not None]
        unranked = [title for title in order if rank_by_title.get(title) is None]
        ranked.sort(key=lambda title: (rank_by_title[title], title.casefold()))
        order = ranked + by_date(unranked)
    else:
        order = by_date(order)
    return [(title, grouped[title]) for title in order]


def _list_path(path: str, query: str) -> str:
    if not query:
        return path
    return path + "?" + urlencode({"q": query})


def _journals_location(q: str = "", **extra: str) -> str:
    params: dict[str, str] = {}
    cleaned = q.strip()
    if cleaned:
        params["q"] = cleaned
    for key, value in extra.items():
        if value:
            params[key] = value
    if not params:
        return "/journals"
    return "/journals?" + urlencode(params)


def _begin_refresh(app: FastAPI) -> bool:
    with app.state.refresh_gate:
        if app.state.library_hold:
            return False
        app.state.refresh_jobs += 1
        app.state.refreshing = True
    return True


def _end_refresh(app: FastAPI) -> None:
    with app.state.refresh_gate:
        app.state.refresh_jobs = max(0, app.state.refresh_jobs - 1)
        app.state.refreshing = app.state.refresh_jobs > 0


_OVERRIDE_NOTE = {
    "flag": "This session was started with --data-dir.",
    "env": "This session was started with PAPER_CART_DATA.",
    "checkout": "This session is using the data folder already in the current directory.",
}


_NOTICE = {
    "select": "Select at least one journal.",
    "select_export": "Select at least one journal to export.",
    "issues": f"Choose between 1 and {MAX_ISSUES} issues.",
    "export_busy": "An export is already running.",
    "export_empty": "No recent issues were found for those journals.",
    "export_config": "Fix the local config, then try the export again.",
}


def _known_issns(request: Request) -> set[str]:
    journals = list_journals(request.app.state.db_path, subscribed_only=True)
    return {issn for journal in journals for issn in journal.issns}


def _mailto(request: Request) -> str | None:
    return load_contact_email(request.app.state.data_dir / "config.toml")


def _config_error(request: Request) -> str | None:
    try:
        _mailto(request)
    except ConfigError as exc:
        return str(exc)
    return None


def _report_error(message: str):
    from paper_cart.refresh import RefreshReport

    return RefreshReport(errors=[message])
