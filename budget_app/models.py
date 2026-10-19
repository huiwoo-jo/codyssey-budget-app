"""Data models for the budget app.

Transaction is the single record type persisted to transactions.jsonl.
Using a dataclass keeps the field contract explicit and typed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

VALID_TYPES = ("income", "expense")


@dataclass
class Transaction:
    id: str
    type: str  # "income" | "expense"
    date: str  # YYYY-MM-DD
    amount: int  # positive integer (currency unit)
    category: str
    memo: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transaction":
        return cls(
            id=data["id"],
            type=data["type"],
            date=data["date"],
            amount=int(data["amount"]),
            category=data["category"],
            memo=data.get("memo", ""),
            tags=list(data.get("tags", [])),
        )


@dataclass
class RecurringRule:
    """[Bonus] A template that generates one Transaction per month.

    applied_months records which months were already generated so that
    running `recurring apply` twice for the same month is a no-op.
    """

    id: str
    type: str
    day: int  # 1-31; clamped to the month's last day when applied
    amount: int
    category: str
    memo: str = ""
    tags: list[str] = field(default_factory=list)
    applied_months: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecurringRule":
        return cls(
            id=data["id"],
            type=data["type"],
            day=int(data["day"]),
            amount=int(data["amount"]),
            category=data["category"],
            memo=data.get("memo", ""),
            tags=list(data.get("tags", [])),
            applied_months=list(data.get("applied_months", [])),
        )
