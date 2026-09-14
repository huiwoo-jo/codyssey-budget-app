"""CSV import/export, using the schema fixed in README.md:

date,type,category,amount,memo,tags  (UTF-8, header row required)
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .exceptions import ValidationError
from .models import Transaction
from .services import SearchFilter, TransactionService

CSV_COLUMNS = ["date", "type", "category", "amount", "memo", "tags"]


def export_csv(service: TransactionService, out_path: Path, filt: SearchFilter) -> int:
    rows = list(service.search(filt))
    rows.reverse()  # export in chronological order
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for txn in rows:
            writer.writerow(
                {
                    "date": txn.date,
                    "type": txn.type,
                    "category": txn.category,
                    "amount": txn.amount,
                    "memo": txn.memo,
                    "tags": ",".join(txn.tags),
                }
            )
    return len(rows)


def import_csv(service: TransactionService, in_path: Path) -> tuple[int, int]:
    if not in_path.exists():
        raise ValidationError(f"파일을 찾을 수 없습니다: {in_path}")

    imported = 0
    skipped = 0
    with in_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in ("date", "type", "category", "amount") if c not in (reader.fieldnames or [])]
        if missing:
            raise ValidationError(f"CSV에 필수 컬럼이 없습니다: {', '.join(missing)}")
        for row in reader:
            try:
                service.add(
                    date=row["date"],
                    type_=row["type"],
                    category=row["category"],
                    amount=row["amount"],
                    memo=row.get("memo", "") or "",
                    tags=row.get("tags", "") or "",
                )
                imported += 1
            except ValidationError:
                skipped += 1
    return imported, skipped
