"""Business logic layer: validation + orchestration over the repositories.

CLI code should only ever call into these services, never touch
storage.py directly, so validation rules live in exactly one place.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass
from typing import Iterator

from .exceptions import ConflictError, NotFoundError, ValidationError
from .models import VALID_TYPES, RecurringRule, Transaction
from .storage import BudgetStore, CategoryStore, RecurringStore, TransactionRepository


def _strict_parse(value: str, fmt: str) -> dt.datetime:
    """strptime accepts "2024-1-5"; we require zero-padded input so stored
    dates compare correctly as strings (search/summary rely on that)."""
    parsed = dt.datetime.strptime(value, fmt)
    if parsed.strftime(fmt) != value:
        raise ValueError(value)
    return parsed


def validate_date(value: str) -> str:
    try:
        _strict_parse(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError(
            "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).",
            hint="예: 2024-01-15",
        ) from exc
    return value


def validate_month(value: str) -> str:
    try:
        _strict_parse(value, "%Y-%m")
    except ValueError as exc:
        raise ValidationError(
            "월 형식이 올바르지 않습니다 (YYYY-MM).",
            hint="예: 2024-01",
        ) from exc
    return value


def month_range(month: str) -> tuple[str, str]:
    """Return (first_day, last_day) of a YYYY-MM month as YYYY-MM-DD strings."""
    year, mon = map(int, validate_month(month).split("-"))
    last = calendar.monthrange(year, mon)[1]
    return f"{month}-01", f"{month}-{last:02d}"


def validate_positive_int(value: int, option: str) -> int:
    if value <= 0:
        raise ValidationError(f"{option} 값은 1 이상이어야 합니다.", hint=f"예: {option} 5")
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
    def __init__(
        self,
        categories: CategoryStore,
        transactions: TransactionRepository,
        recurring: RecurringStore | None = None,
    ) -> None:
        self.categories = categories
        self.transactions = transactions
        self.recurring = recurring

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
        if self.recurring and any(rule.category == name for rule in self.recurring.list()):
            raise ConflictError(
                f"카테고리 '{name}'을(를) 사용 중인 반복 내역이 있어 삭제할 수 없습니다.",
                hint="recurring remove로 해당 반복 내역을 먼저 삭제하세요.",
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

    def __post_init__(self) -> None:
        # Validate once up front so a typo (e.g. --type expnse) is an error,
        # not a silent "no results".
        if self.date_from:
            validate_date(self.date_from)
        if self.date_to:
            validate_date(self.date_to)
        if self.type_:
            validate_type(self.type_)
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError("--from 날짜가 --to 날짜보다 늦습니다.", hint="예: --from 2024-01-01 --to 2024-01-31")

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


class RecurringService:
    """[Bonus] Register monthly recurring items (salary, rent...) and
    generate the matching transactions for a given month."""

    def __init__(
        self,
        rules: RecurringStore,
        transactions: TransactionService,
        categories: CategoryService,
    ) -> None:
        self.rules = rules
        self.transactions = transactions
        self.categories = categories

    def add(self, type_: str, day: str, category: str, amount: str, memo: str = "", tags: str = "") -> RecurringRule:
        try:
            day_i = int(day)
        except ValueError:
            day_i = 0
        if not 1 <= day_i <= 31:
            raise ValidationError("day는 1~31 사이 숫자여야 합니다.", hint="예: --day 25")
        self.categories.require_exists(category)
        rule = RecurringRule(
            id=self.rules.next_id(),
            type=validate_type(type_),
            day=day_i,
            amount=validate_amount(amount),
            category=category,
            memo=memo,
            tags=parse_tags(tags),
        )
        self.rules.save_all(self.rules.list() + [rule])
        return rule

    def list(self) -> list[RecurringRule]:
        return self.rules.list()

    def remove(self, rule_id: str) -> None:
        rules = self.rules.list()
        remaining = [r for r in rules if r.id != rule_id]
        if len(remaining) == len(rules):
            raise NotFoundError(
                f"반복 내역을 찾을 수 없습니다 (id={rule_id})",
                hint="recurring list로 존재하는 id를 확인하세요.",
            )
        self.rules.save_all(remaining)

    def apply(self, month: str) -> tuple[list[Transaction], int]:
        """Create this month's transactions. Returns (created, skipped_already_applied)."""
        _, last_day = month_range(month)
        last_dom = int(last_day[-2:])
        rules = self.rules.list()
        created: list[Transaction] = []
        skipped = 0
        for rule in rules:
            if month in rule.applied_months:
                skipped += 1
                continue
            day = min(rule.day, last_dom)  # e.g. day 31 -> Feb 28/29
            created.append(
                self.transactions.add(
                    date=f"{month}-{day:02d}",
                    type_=rule.type,
                    category=rule.category,
                    amount=str(rule.amount),
                    memo=rule.memo,
                    tags=",".join(rule.tags),
                )
            )
            rule.applied_months.append(month)
        self.rules.save_all(rules)
        return created, skipped
