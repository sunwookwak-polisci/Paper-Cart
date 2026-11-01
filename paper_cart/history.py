"""Undo and redo for paper moves. History lasts until Paper Cart quits."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from paper_cart.db import StatusChange, replay_changes

LIMIT = 100
TITLE_CHARS = 60

# Read as "Undo dismissing “A paper”" or "Redo moving 3 papers to Reading".
PHRASES = {
    "new": "moving {} to New",
    "read_later": "moving {} to Read later",
    "reading": "moving {} to Reading",
    "done": "moving {} to Done",
    "dismissed": "dismissing {}",
    "removed": "removing {}",
}


@dataclass(frozen=True)
class Step:
    """One click: a single paper or a whole bulk move."""

    changes: tuple[StatusChange, ...]

    def describe(self) -> str:
        targets = {change.after for change in self.changes}
        phrase = PHRASES.get(targets.pop(), "moving {}") if len(targets) == 1 else "moving {}"
        if len(self.changes) == 1:
            title = " ".join(self.changes[0].title.split())
            if len(title) > TITLE_CHARS:
                title = title[: TITLE_CHARS - 1].rstrip() + "…"
            subject = f"“{title}”"
        else:
            subject = f"{len(self.changes)} papers"
        return phrase.format(subject)


class History:
    """Undo and redo stacks for one library file at a time."""

    def __init__(self, limit: int = LIMIT) -> None:
        self._lock = threading.Lock()
        self._limit = limit
        self._db_path: Path | None = None
        self._undo: list[Step] = []
        self._redo: list[Step] = []

    def record(self, db_path: Path, changes: Sequence[StatusChange]) -> None:
        if not changes:
            return
        with self._lock:
            self._follow(db_path)
            self._undo.append(Step(tuple(changes)))
            del self._undo[: -self._limit]
            self._redo.clear()

    def undo(self, db_path: Path) -> Step | None:
        return self._replay(db_path, undo=True)

    def redo(self, db_path: Path) -> Step | None:
        return self._replay(db_path, undo=False)

    def labels(self, db_path: Path) -> tuple[str, str]:
        """What Undo and Redo would do next, or "" when there is nothing."""
        with self._lock:
            self._follow(db_path)
            undo = self._undo[-1].describe() if self._undo else ""
            redo = self._redo[-1].describe() if self._redo else ""
        return undo, redo

    def _replay(self, db_path: Path, *, undo: bool) -> Step | None:
        with self._lock:
            self._follow(db_path)
            source, target = (self._undo, self._redo) if undo else (self._redo, self._undo)
            while source:
                step = source.pop()
                applied = replay_changes(db_path, step.changes, undo=undo)
                if applied:
                    done = Step(tuple(applied))
                    target.append(done)
                    return done
            return None

    def _follow(self, db_path: Path) -> None:
        # Switching or renaming the library starts a fresh history.
        if self._db_path != db_path:
            self._db_path = db_path
            self._undo.clear()
            self._redo.clear()
