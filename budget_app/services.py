"""Business logic layer: validation + orchestration over the repositories.

CLI code should only ever call into these services, never touch
storage.py directly, so validation rules live in exactly one place.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .exceptions import ConflictError, ValidationError
from .models import VALID_TYPES, Transaction
from .storage import BudgetStore, CategoryStore, TransactionRepository


def validate_date(value: str) -> str:
    try:
        dt.datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError(
            "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).",
            hint="예: 2024-01-15",
        ) from exc
    return value


def validate_month(value: str) -> str:
    try:
        dt.datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValidationError(
            "월 형식이 올바르지 않습니다 (YYYY-MM).",
            hint="예: 2024-01",
        ) from exc
    return value


def validate_amount(value: str) -> int:
    try:
        amount = int(value)
    except ValueError as exc:
        raise ValidationError(
            "금액은 숫자여야 합니다.", hint="예: 15000"
        ) from exc
    if amount <= 0:
        raise ValidationError(
            "금액은 0보다 큰 양수여야 합니다.", hint="예: 15000"
        )
    return amount


def validate_type(value: str) -> str:
    if value not in VALID_TYPES:
        raise ValidationError(
            f"type은 {'/'.join(VALID_TYPES)} 중 하나여야 합니다.",
            hint="예: expense",
        )
    return value


def parse_tags(value: str) -> list[str]:
    return [t.strip() for t in value.split(",") if t.strip()]


class CategoryService:
    def __init__(self, categories: CategoryStore, transactions: TransactionRepository) -> None:
        self.categories = categories
        self.transactions = transactions

    def list(self) -> list[str]:
        return self.categories.list()

    def add(self, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValidationError("카테고리명을 입력하세요.")
        self.categories.add(name)

    def remove(self, name: str) -> None:
        if not self.categories.exists(name):
            raise ValidationError(f"존재하지 않는 카테고리입니다 (category={name})")
        if self.transactions.category_in_use(name):
            raise ConflictError(
                f"카테고리 '{name}'을(를) 사용 중인 거래가 있어 삭제할 수 없습니다.",
                hint="해당 거래를 먼저 update로 다른 카테고리로 옮기세요.",
            )
        self.categories.remove(name)

    def require_exists(self, name: str) -> None:
        if not self.categories.exists(name):
            raise ValidationError(
                f"등록되지 않은 카테고리입니다 (category={name})",
                hint="category add 로 먼저 등록하세요.",
            )


@dataclass
class SearchFilter:
    date_from: str | None = None
    date_to: str | None = None
    category: str | None = None
    type_: str | None = None
    query: str | None = None
    tag: str | None = None

    def matches(self, txn: Transaction) -> bool:
        if self.date_from and txn.date < self.date_from:
            return False
        if self.date_to and txn.date > self.date_to:
            return False
        if self.category and txn.category != self.category:
            return False
        if self.type_ and txn.type != self.type_:
            return False
        if self.query and self.query.lower() not in txn.memo.lower():
            return False
        if self.tag and self.tag not in txn.tags:
            return False
        return True


class TransactionService:
    def __init__(self, transactions: TransactionRepository, categories: CategoryService) -> None:
        self.transactions = transactions
        self.categories = categories

    def add(
        self,
        date: str,
        type_: str,
        category: str,
        amount: str,
        memo: str = "",
        tags: str = "",
    ) -> Transaction:
        date = validate_date(date)
        type_ = validate_type(type_)
        amount_i = validate_amount(amount)
        self.categories.require_exists(category)
        txn = Transaction(
            id=self.transactions.next_id(),
            type=type_,
            date=date,
            amount=amount_i,
            category=category,
            memo=memo,
            tags=parse_tags(tags),
        )
        self.transactions.add(txn)
        return txn

    def list_latest(self, limit: int = 10) -> Iterator[Transaction]:
        count = 0
        for txn in self.transactions.iter_newest_first():
            if count >= limit:
                break
            yield txn
            count += 1

    def search(self, filt: SearchFilter) -> Iterator[Transaction]:
        for txn in self.transactions.iter_newest_first():
            if filt.matches(txn):
                yield txn

    def update(
        self,
        txn_id: str,
        date: str | None = None,
        type_: str | None = None,
        category: str | None = None,
        amount: str | None = None,
        memo: str | None = None,
        tags: str | None = None,
    ) -> Transaction:
        changes: dict[str, object] = {}
        if date is not None:
            changes["date"] = validate_date(date)
        if type_ is not None:
            changes["type"] = validate_type(type_)
        if category is not None:
            self.categories.require_exists(category)
            changes["category"] = category
        if amount is not None:
            changes["amount"] = validate_amount(amount)
        if memo is not None:
            changes["memo"] = memo
        if tags is not None:
            changes["tags"] = parse_tags(tags)
        return self.transactions.update(txn_id, **changes)

    def delete(self, txn_id: str) -> None:
        self.transactions.delete(txn_id)


@dataclass
class MonthSummary:
    month: str
    total_income: int
    total_expense: int
    balance: int
    top_categories: list[tuple[str, int]]
    budget: int | None
    usage_pct: float | None
    over_budget: bool


class BudgetService:
    def __init__(self, budgets: BudgetStore, transactions: TransactionRepository) -> None:
        self.budgets = budgets
        self.transactions = transactions

    def set_budget(self, month: str, amount: str) -> int:
        month = validate_month(month)
        amount_i = validate_amount(amount)
        self.budgets.set(month, amount_i)
        return amount_i

    def summarize(self, month: str, top: int = 3) -> MonthSummary:
        month = validate_month(month)
        income = 0
        expense = 0
        by_category: dict[str, int] = {}
        for txn in self.transactions.iter_all():
            if not txn.date.startswith(month):
                continue
            if txn.type == "income":
                income += txn.amount
            else:
                expense += txn.amount
                by_category[txn.category] = by_category.get(txn.category, 0) + txn.amount

        top_categories = sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)[:top]
        budget = self.budgets.get(month)
        usage_pct = round(expense / budget * 100, 1) if budget else None
        over_budget = bool(budget and expense > budget)
        return MonthSummary(
            month=month,
            total_income=income,
            total_expense=expense,
            balance=income - expense,
            top_categories=top_categories,
            budget=budget,
            usage_pct=usage_pct,
            over_budget=over_budget,
        )
