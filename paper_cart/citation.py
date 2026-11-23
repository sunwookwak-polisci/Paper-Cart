"""Reference-list citations for one paper, in APA 7th or Chicago author-date 17th."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

from paper_cart.db import Paper

STYLES = {"apa": "APA 7th", "chicago": "Chicago author-date 17th"}
DEFAULT_STYLE = "apa"

# Lowercase words that start a family name in "Given Family" text, as in "Ludwig van Beethoven".
_PARTICLES = {
    "al", "bin", "da", "das", "de", "del", "della", "der", "di", "dos", "du",
    "el", "la", "le", "st.", "ten", "ter", "van", "von",
}
_DASHES = re.compile(r"\s*[-‐‑‒–—]+\s*")
_SPACE = re.compile(r"\s+")
# A run of letters after a space, hyphen, apostrophe or the start: "o'neil-smith" -> 3 words.
_WORD = re.compile(r"[^\W\d_]+")


@dataclass(frozen=True)
class Name:
    given: str = ""
    family: str = ""
    suffix: str = ""
    literal: str = ""


@dataclass(frozen=True)
class Citation:
    text: str
    html: str


@dataclass(frozen=True)
class _Part:
    text: str
    italic: bool = False


def normalize_style(value: str) -> str:
    return value if value in STYLES else DEFAULT_STYLE


def cite(paper: Paper, style: str) -> Citation:
    fields = _fields(paper)
    names = _names(paper, fields)
    if normalize_style(style) == "chicago":
        parts = _chicago(paper, fields, names)
    else:
        parts = _apa(paper, fields, names)
    return Citation(
        text="".join(part.text for part in parts),
        html="".join(
            f"<i>{html.escape(part.text)}</i>" if part.italic else html.escape(part.text)
            for part in parts
        ),
    )


def _fields(paper: Paper) -> dict:
    if not paper.citation_data:
        return {}
    try:
        fields = json.loads(paper.citation_data)
    except ValueError:
        return {}
    return fields if isinstance(fields, dict) else {}


def _names(paper: Paper, fields: dict) -> list[Name]:
    stored = fields.get("authors")
    if isinstance(stored, list) and stored:
        names = []
        for item in stored:
            if not isinstance(item, dict):
                continue
            if item.get("name"):
                names.append(Name(literal=_clean(item["name"])))
            else:
                names.append(
                    Name(
                        given=_name_case(item.get("given", "")),
                        family=_name_case(item.get("family", "")),
                        suffix=_clean(item.get("suffix", "")),
                    )
                )
        return [name for name in names if name.literal or name.family or name.given]
    # Papers Crossref has not been asked about yet only have "Given Family, Given Family".
    return [split_name(part) for part in paper.authors.split(",") if part.strip()]


def split_name(text: str) -> Name:
    words = _name_case(text).split(" ")
    if len(words) == 1:
        return Name(family=words[0])
    start = len(words) - 1
    while start > 1 and words[start - 1].lower() in _PARTICLES:
        start -= 1
    return Name(given=" ".join(words[:start]), family=" ".join(words[start:]))


def _name_case(value: object) -> str:
    """Some publishers send names in capitals ("DICKSON"); write them as names."""
    text = _clean(value)
    if not text.isupper() or len(text.replace(".", "").replace(" ", "")) <= 2:
        return text
    return _WORD.sub(lambda match: _word_case(match.group(0)), text.lower())


def _word_case(word: str) -> str:
    word = word[0].upper() + word[1:]
    if word.startswith("Mc") and len(word) > 2:
        word = "Mc" + word[2].upper() + word[3:]
    return word


def _clean(value: object) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()


def _title(paper: Paper, fields: dict) -> str:
    title = _clean(paper.title)
    subtitle = _clean(fields.get("subtitle", ""))
    if subtitle and subtitle.casefold() not in title.casefold():
        title = title.rstrip(":")
        title = f"{title} {subtitle}" if title.endswith(("?", "!")) else f"{title}: {subtitle}"
    return title


def _year(paper: Paper) -> str:
    date = paper.published_date or ""
    return date[:4] if len(date) >= 4 and date[:4].isdigit() else "n.d."


def _pages(fields: dict) -> str:
    return _DASHES.sub("–", _clean(fields.get("page", "")))


def _end(text: str, mark: str = ".") -> str:
    """Close a sentence once, without doubling a period or covering ? and !."""
    text = text.rstrip()
    return text if text.endswith((".", "?", "!")) else text + mark


def _doi(paper: Paper) -> str:
    return f"https://doi.org/{paper.doi}"


# APA 7th, section 9.8 and 10.1.
def _apa(paper: Paper, fields: dict, names: list[Name]) -> list[_Part]:
    title = _end(_title(paper, fields))
    date = f"({_year(paper)})."
    parts = [_Part(f"{_end(_apa_names(names))} {date} {title} ")] if names else [
        _Part(f"{title} {date} ")
    ]
    volume = _clean(fields.get("volume", ""))
    issue = _clean(fields.get("issue", ""))
    pages = _pages(fields)
    article = _clean(fields.get("article_number", ""))
    parts.append(_Part(paper.journal_title, italic=True))
    if volume:
        parts.append(_Part(", "))
        parts.append(_Part(volume, italic=True))
        if issue:
            parts.append(_Part(f"({issue})"))
    if pages:
        parts.append(_Part(f", {pages}"))
    elif article:
        parts.append(_Part(f", Article {article}"))
    parts.append(_Part(f". {_doi(paper)}"))
    return parts


def _apa_names(names: list[Name]) -> str:
    written = [_apa_name(name) for name in names]
    if len(written) == 1:
        return written[0]
    if len(written) > 20:
        return ", ".join(written[:19]) + ", . . . " + written[-1]
    return ", ".join(written[:-1]) + ", & " + written[-1]


def _apa_name(name: Name) -> str:
    if name.literal:
        return name.literal
    if not name.family:
        return name.given
    text = name.family
    initials = _initials(name.given)
    if initials:
        text += f", {initials}"
    if name.suffix:
        text += f", {name.suffix}"
    return text


def _initials(given: str) -> str:
    """"Sun-Woo" -> "S.-W.", "Mary Jane" -> "M. J.", "J.R.R." -> "J. R. R."."""
    words = []
    for word in given.replace(".", ". ").split():
        pieces = [piece for piece in word.split("-") if piece]
        letters = [f"{piece[0].upper()}." for piece in pieces if piece[0].isalpha()]
        if letters:
            words.append("-".join(letters))
    return " ".join(words)


# The Chicago Manual of Style, 17th edition, sections 15.9 and 15.47.
def _chicago(paper: Paper, fields: dict, names: list[Name]) -> list[_Part]:
    title = _end(_title(paper, fields))
    year = _year(paper)
    if names:
        parts = [_Part(f"{_end(_chicago_names(names))} {_end(year)} “{title}” ")]
    else:
        parts = [_Part(f"“{title}” {_end(year)} ")]
    volume = _clean(fields.get("volume", ""))
    issue = _clean(fields.get("issue", ""))
    pages = _chicago_pages(_pages(fields)) or _clean(fields.get("article_number", ""))
    parts.append(_Part(paper.journal_title, italic=True))
    if volume:
        tail = f" {volume}"
        if issue:
            tail += f" ({issue})"
    elif issue:
        tail = f", no. {issue}"
    else:
        tail = ""
    if pages:
        tail += f": {pages}"
    parts.append(_Part(f"{tail}. {_doi(paper)}."))
    return parts


def _chicago_names(names: list[Name]) -> str:
    if len(names) > 10:
        listed = [_chicago_name(name, first=index == 0) for index, name in enumerate(names[:7])]
        return ", ".join(listed) + ", et al."
    written = [_chicago_name(name, first=index == 0) for index, name in enumerate(names)]
    if len(written) == 1:
        return written[0]
    return ", ".join(written[:-1]) + ", and " + written[-1]


def _chicago_name(name: Name, *, first: bool) -> str:
    if name.literal:
        return name.literal
    if not name.family or not name.given:
        return name.family or name.given
    if first:
        text = f"{name.family}, {name.given}"
        return f"{text}, {name.suffix}" if name.suffix else text
    text = f"{name.given} {name.family}"
    return f"{text} {name.suffix}" if name.suffix else text


def _chicago_pages(pages: str) -> str:
    """Shorten the second page number the Chicago way (9.64): 611–39, 101–8, 1087–89."""
    first, dash, last = pages.partition("–")
    if not dash or not first.isdigit() or not last.isdigit() or int(last) <= int(first):
        return pages
    start = int(first)
    if start < 100 or start % 100 == 0 or len(last) != len(first):
        return pages
    same = 0
    while same < len(first) and first[same] == last[same]:
        same += 1
    changed = len(last) - same
    if start % 100 < 10:
        return f"{first}–{last[same:]}"
    if len(first) == 4 and changed >= 3:
        return pages
    return f"{first}–{last[-max(2, changed):]}"
