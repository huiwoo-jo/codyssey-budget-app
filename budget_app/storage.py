"""File-based persistence layer (JSONL, one file per entity).

Two access patterns are provided:
  * iter_forward  - plain top-to-bottom generator (insertion order)
  * iter_reverse  - streaming generator that yields newest-first without
                    ever loading the whole file into memory, by reading
                    the file backwards in fixed-size byte chunks.

Writes that must touch existing rows (update/delete) rewrite the file to
a temporary path and then atomically replace the original with os.replace,
so a crash mid-write can never leave a half-written data file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator

from .exceptions import ConflictError, NotFoundError
from .models import RecurringRule, Transaction


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def iter_forward(path: Path) -> Iterator[dict[str, Any]]:
    """Stream JSONL rows top to bottom without loading the whole file."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def iter_reverse(path: Path, buf_size: int = 8192) -> Iterator[str]:
    """Stream raw lines of a text file from last to first.

    Reads the file backwards in buf_size chunks so memory use stays
    bounded regardless of file size (used for "newest first" listing).
    """
    if not path.exists():
        return
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        file_size = remaining = f.tell()
        offset = 0
        segment = b""
        while remaining > 0:
            read_size = min(buf_size, remaining)
            offset += read_size
            f.seek(file_size - offset)
            chunk = f.read(read_size)
            remaining -= read_size
            lines = (chunk + segment).split(b"\n")
            segment = lines[0]
            for raw in reversed(lines[1:]):
                if raw:
                    yield raw.decode("utf-8")
        if segment:
            yield segment.decode("utf-8")


def append_line(path: Path, row: dict[str, Any]) -> None:
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rewrite_all(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Atomically replace the file's contents (used by update/delete).

    rows may be a generator that is still reading the original file: we only
    ever write to the temp file, and the original is swapped in one
    os.replace. If anything raises mid-way, the temp file is discarded and
    the original file is left untouched.
    """
    _ensure_parent(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())  # data must be on disk before the rename
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, path)


def _not_found(txn_id: str) -> NotFoundError:
    return NotFoundError(
        f"거래를 찾을 수 없습니다 (id={txn_id})",
        hint="list 명령으로 존재하는 id를 확인하세요.",
    )


class TransactionRepository:
    """Persists Transaction records to transactions.jsonl."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "transactions.jsonl"
        # Last issued id number. Kept separately so deleting the newest
        # transaction never causes its id to be handed out again.
        self.seq_path = data_dir / "transactions.seq"

    def _last_issued(self) -> int:
        from_seq = int(self.seq_path.read_text()) if self.seq_path.exists() else 0
        from_file = 0
        for raw in iter_reverse(self.path):
            from_file = int(str(json.loads(raw)["id"]).split("-")[-1])
            break
        return max(from_seq, from_file)

    def next_id(self) -> str:
        return f"TX-{self._last_issued() + 1:06d}"

    def add(self, txn: Transaction) -> None:
        append_line(self.path, txn.to_dict())
        self.seq_path.write_text(str(int(txn.id.split("-")[-1])))

    def iter_newest_first(self) -> Iterator[Transaction]:
        for raw in iter_reverse(self.path):
            yield Transaction.from_dict(json.loads(raw))

    def get(self, txn_id: str) -> Transaction:
        for txn in self.iter_all():
            if txn.id == txn_id:
                return txn
        raise _not_found(txn_id)

    def iter_all(self) -> Iterator[Transaction]:
        for row in iter_forward(self.path):
            yield Transaction.from_dict(row)

    # update/delete stream old file -> temp file row by row (memory stays O(1));
    # raising at the end for a missing id makes rewrite_all discard the temp file.

    def update(self, txn_id: str, **changes: Any) -> Transaction:
        updated: list[Transaction] = []

        def rows() -> Iterator[dict[str, Any]]:
            for row in iter_forward(self.path):
                if row["id"] == txn_id:
                    row.update({k: v for k, v in changes.items() if v is not None})
                    updated.append(Transaction.from_dict(row))
                yield row
            if not updated:
                raise _not_found(txn_id)

        rewrite_all(self.path, rows())
        return updated[0]

    def delete(self, txn_id: str) -> None:
        def rows() -> Iterator[dict[str, Any]]:
            found = False
            for row in iter_forward(self.path):
                if row["id"] == txn_id:
                    found = True
                    continue
                yield row
            if not found:
                raise _not_found(txn_id)

        rewrite_all(self.path, rows())

    def category_in_use(self, category: str) -> bool:
        return any(txn.category == category for txn in self.iter_all())


class CategoryStore:
    """Persists category names to categories.jsonl."""

    DEFAULTS = ("food", "transport", "rent", "etc")

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "categories.jsonl"
        if not self.path.exists():
            rewrite_all(self.path, [{"name": name} for name in self.DEFAULTS])

    def list(self) -> list[str]:
        return [row["name"] for row in iter_forward(self.path)]

    def exists(self, name: str) -> bool:
        return name in self.list()

    def add(self, name: str) -> None:
        names = self.list()
        if name in names:
            raise ConflictError(
                f"이미 존재하는 카테고리입니다 (category={name})",
                hint="category list로 기존 카테고리를 확인하세요.",
            )
        rows = [{"name": n} for n in names] + [{"name": name}]
        rewrite_all(self.path, rows)

    def remove(self, name: str) -> None:
        names = [n for n in self.list() if n != name]
        rewrite_all(self.path, [{"name": n} for n in names])


class BudgetStore:
    """Persists one monthly budget amount per month to budgets.jsonl."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "budgets.jsonl"

    def get(self, month: str) -> int | None:
        for row in iter_forward(self.path):
            if row["month"] == month:
                return int(row["amount"])
        return None

    def set(self, month: str, amount: int) -> None:
        rows = [row for row in iter_forward(self.path) if row["month"] != month]
        rows.append({"month": month, "amount": amount})
        rewrite_all(self.path, rows)


class RecurringStore:
    """[Bonus] Persists recurring-transaction rules to recurring.jsonl."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "recurring.jsonl"

    def list(self) -> list[RecurringRule]:
        return [RecurringRule.from_dict(row) for row in iter_forward(self.path)]

    def save_all(self, rules: list[RecurringRule]) -> None:
        rewrite_all(self.path, [rule.to_dict() for rule in rules])

    def next_id(self) -> str:
        nums = [int(rule.id.split("-")[-1]) for rule in self.list()]
        return f"RC-{max(nums, default=0) + 1:03d}"
