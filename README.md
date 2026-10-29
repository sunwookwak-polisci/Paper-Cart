# Paper Cart

Paper Cart follows academic journals you select and keeps a private reading list on your computer. New articles come from the [Crossref](https://api.crossref.org) works API, the same source [Paper Picnic](https://paper-picnic.com/about) uses. Journal RSS is not part of this version.

You run it locally. Nothing stays online after you quit, and there is no account server to host.

## Install

Install Paper Cart with [uv](https://docs.astral.sh/uv/):

```bash
brew install uv
uv tool install git+https://github.com/sunwookwak-polisci/Paper-Cart
paper-cart
```

On Linux, install uv with its [installer](https://docs.astral.sh/uv/getting-started/installation/) instead of Homebrew. Update later with `uv tool upgrade paper-cart`. The Homebrew formula and release steps are in [`packaging/homebrew/`](packaging/homebrew/README.md).

## Run from a checkout

Install [uv](https://docs.astral.sh/uv/), then:

```bash
git clone https://github.com/sunwookwak-polisci/Paper-Cart.git
cd Paper-Cart
uv sync
uv run paper-cart
```

`uv run python -m paper_cart` still works too.

The app listens on [http://127.0.0.1:8000](http://127.0.0.1:8000) and opens that page in your browser. If Paper Cart is already running, starting it again just opens the existing page. If another program holds port 8000, it uses the next free port and prints the address. Press Quit in the app, or Ctrl+C in the terminal, to stop it.

Updates run in the background while the app is open: once at startup, and again when you press Update. You can keep reading while papers load; the list refreshes when the update finishes.

## Where your library lives

On a Mac the library is kept in `~/Library/Application Support/Paper Cart` (on Linux, `~/.local/share/paper-cart`). The folder is printed when Paper Cart starts, and upgrading or reinstalling leaves it alone.

Settings in the app can choose a different folder. That choice is saved in the per-user folder and used the next time Paper Cart starts. The previous library stays where it is. A chosen folder with no library yet starts empty. `paper-cart --data-dir /path/to/folder` and `PAPER_CART_DATA` override the saved folder. A checkout that already has `data/library.sqlite` keeps using it when started from the repository root.

One folder can hold several library files. Settings lists those sqlite files and chooses which one is in use. That choice is saved in the folder, and the next start opens the same file. Export downloads the file in use. Import adds a sqlite file in that folder, or replaces the file with the same name after you confirm and the upload checks out as a library. The previous file is kept until the upload is valid, and the other sqlite files stay in place. Rename changes one file's name in that folder. Empty names and names that match an existing file are refused. If you rename the file in use, the next start still opens it. Switching, renaming, and importing take effect without a restart. Changing the folder still waits until the next start.

Optional: to use Crossref's polite pool, create `config.toml` in the library folder with your `contact_email`. [`config.example.toml`](config.example.toml) shows the format. The address is sent only to Crossref.

## How updates work

Search finds journals through Crossref `GET /journals?query=`. Select one or more results, add them to the cart, and subscribe once. That returns immediately. Recent papers for the new journals are fetched in the background and show up under New. Update still checks every subscribed journal. Both loads use `journal-article` records for each ISSN with `from-created-date` and `from-pub-date`. The first check looks back 30 days. Later checks look back 14 days, so a paper indexed late can still appear. Papers are stored by DOI. A later update refreshes metadata and leaves your reading status alone.

Titles that are editorials, corrections, errata, retractions, tables of contents, or issue information are skipped. Abstracts are shown when Crossref includes them. Some publishers omit abstracts; the DOI link is still there.

## Reading progress

Each paper has one status. Choosing a status is the bookmark.

- **New** — just arrived
- **Read later**
- **Reading**
- **Done**
- **Dismissed** — hidden from New, and not imported again as new
- **Removed** — out of the other lists. A paper can be removed only from Dismissed. The library link is a trash icon.

## Finding papers

Each list has a keyword search for the papers on that list. Every word has to match the title, authors, abstract, journal name, or DOI.

Tick the box beside papers, or Select all shown, to move several at once. Combined with a keyword search, this dismisses or files a whole batch in one step.

Papers are ordered by date, newest first. Group by journal is off until you turn it on. Group order can follow the date of the newest paper in the group, alphabetical order, or a custom order. Drag a journal by its handle, or use the arrows, to set that custom order. The journal order list can be folded, and it stays folded after that choice is saved.

On the Journals page you can export abstracts for one or more subscribed journals. Choose how many recent issues to include, counting back from the latest. The download is a Markdown file of titles, authors, DOIs, and abstracts from Crossref. It includes papers older than New. Reading status is left alone. Some publishers omit abstracts; those papers are still listed.

## Tests

```bash
uv run pytest
```

## Keeping your data out of commits

In a checkout, `data/` and any `.sqlite` file are gitignored, so a library or `config.toml` kept there, including a contact email, stays out of commits. Keep journal lists, reading status, and email addresses out of source, tests, and docs.

## License

Paper Cart is released under the [MIT License](LICENSE). The bundled Source Sans 3 and Source Serif 4 fonts keep their own SIL Open Font License, included in [`paper_cart/static/fonts/`](paper_cart/static/fonts/).
