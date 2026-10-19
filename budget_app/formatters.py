"""[Bonus] Console table output without external libraries.

Korean (East Asian Wide) characters occupy two terminal columns, so plain
str.ljust() misaligns columns. display_width() counts real columns.
"""
from __future__ import annotations

import unicodedata
from typing import Sequence

from .models import RecurringRule, Transaction

TXN_HEADERS = ("ID", "날짜", "타입", "카테고리", "금액", "메모", "태그")
RECURRING_HEADERS = ("ID", "매월", "타입", "카테고리", "금액", "메모", "적용된 월")


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, width: int, right: bool = False) -> str:
    gap = " " * (width - display_width(text))
    return gap + text if right else text + gap


def format_table(headers: Sequence[str], rows: Sequence[Sequence[str]], right_cols: Sequence[int] = ()) -> str:
    widths = [display_width(h) for h in headers]
    for row in rows:
        widths = [max(w, display_width(cell)) for w, cell in zip(widths, row)]

    def line(cells: Sequence[str]) -> str:
        return " | ".join(pad(c, w, i in right_cols) for i, (c, w) in enumerate(zip(cells, widths))).rstrip()

    separator = "-+-".join("-" * w for w in widths)
    return "\n".join([line(headers), separator, *(line(r) for r in rows)])


def txn_row(txn: Transaction) -> list[str]:
    return [txn.id, txn.date, txn.type, txn.category, f"{txn.amount:,}", txn.memo, ",".join(txn.tags)]


def format_transactions(txns: Sequence[Transaction]) -> str:
    return format_table(TXN_HEADERS, [txn_row(t) for t in txns], right_cols=(4,))


def format_recurring(rules: Sequence[RecurringRule]) -> str:
    rows = [
        [r.id, f"{r.day}일", r.type, r.category, f"{r.amount:,}", r.memo, ",".join(r.applied_months) or "-"]
        for r in rules
    ]
    return format_table(RECURRING_HEADERS, rows, right_cols=(4,))
