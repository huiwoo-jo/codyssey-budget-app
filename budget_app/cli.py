"""Command-line interface: argument parsing + interactive prompts only.

No business rules live here - every command delegates validation and
persistence to services.py / storage.py.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from .csv_io import export_csv, import_csv
from .decorators import handle_errors, log_execution, measure_time
from .exceptions import AppError, ValidationError
from .formatters import format_recurring, format_transactions
from .models import Transaction
from .services import (
    BudgetService,
    CategoryService,
    RecurringService,
    SearchFilter,
    TransactionService,
    month_range,
    validate_amount,
    validate_date,
    validate_positive_int,
    validate_type,
)
from .storage import BudgetStore, CategoryStore, RecurringStore, TransactionRepository

DEFAULT_DATA_DIR = "./data"
PAGE_SIZE = 50  # search prints one aligned table per page so output stays streamed

T = TypeVar("T")


def prompt(label: str, validator: Callable[[str], T] | None = None, default: str | None = None) -> T | str:
    """Ask until the validator accepts the input (re-prompt on error)."""
    while True:
        raw = input(f"{label}: ").strip()
        if not raw and default is not None:
            raw = default
        if validator is None:
            return raw
        try:
            return validator(raw)
        except AppError as exc:
            print(f"[오류] {exc.message}")
            if exc.hint:
                print(f"[힌트] {exc.hint}")


def print_pages(txns: Iterator[Transaction], empty_message: str) -> None:
    """Print a streamed iterator as aligned tables of PAGE_SIZE rows."""
    printed = False
    while page := list(islice(txns, PAGE_SIZE)):
        if printed:
            print()
        print(format_transactions(page))
        printed = True
    if not printed:
        print(empty_message)


def build_context(data_dir: str) -> tuple[CategoryService, TransactionService, BudgetService]:
    data_path = Path(data_dir)
    if data_path.exists() and not data_path.is_dir():
        raise ValidationError(f"--data-dir 경로가 폴더가 아닙니다: {data_path}", hint="폴더 경로를 지정하세요.")
    categories = CategoryStore(data_path)
    transactions = TransactionRepository(data_path)
    budgets = BudgetStore(data_path)
    category_service = CategoryService(categories, transactions, RecurringStore(data_path))
    transaction_service = TransactionService(transactions, category_service)
    budget_service = BudgetService(budgets, transactions)
    return category_service, transaction_service, budget_service


def build_recurring(data_dir: str) -> RecurringService:
    categories, transactions, _ = build_context(data_dir)
    return RecurringService(RecurringStore(Path(data_dir)), transactions, categories)


def existing_category(categories: CategoryService) -> Callable[[str], str]:
    def check(value: str) -> str:
        categories.require_exists(value)
        return value

    return check


@handle_errors
@log_execution
@measure_time
def cmd_add(args: argparse.Namespace) -> int:
    categories, transactions, _ = build_context(args.data_dir)
    print("사용 가능한 카테고리:", ", ".join(categories.list()))
    # each field is validated right after it is typed, so only that field is re-asked
    date = prompt("날짜(YYYY-MM-DD)", validate_date)
    type_ = prompt("타입(income/expense)", validate_type)
    category = prompt("카테고리", existing_category(categories))
    amount = prompt("금액(양수)", lambda v: str(validate_amount(v)))
    memo = prompt("메모(선택)", default="")
    tags = prompt("태그(쉼표로 구분, 없으면 엔터)", default="")
    txn = transactions.add(date, type_, category, amount, memo, tags)
    print(f"[저장 완료] id={txn.id}")
    return 0


@handle_errors
@log_execution
def cmd_list(args: argparse.Namespace) -> int:
    validate_positive_int(args.limit, "--limit")
    _, transactions, _ = build_context(args.data_dir)
    print_pages(transactions.list_latest(limit=args.limit), "[정보] 거래 내역이 없습니다.")
    return 0


@handle_errors
@log_execution
def cmd_search(args: argparse.Namespace) -> int:
    _, transactions, _ = build_context(args.data_dir)
    filt = SearchFilter(
        date_from=args.from_,
        date_to=args.to,
        category=args.category,
        type_=args.type,
        query=args.q,
        tag=args.tag,
    )
    print_pages(transactions.search(filt), "[정보] 조건에 맞는 거래가 없습니다.")
    return 0


@handle_errors
@log_execution
def cmd_summary(args: argparse.Namespace) -> int:
    validate_positive_int(args.top, "--top")
    _, _, budget_service = build_context(args.data_dir)
    summary = budget_service.summarize(args.month, top=args.top)
    if summary.total_income == 0 and summary.total_expense == 0:
        print(f"[정보] {args.month} 데이터 없음")
        return 0
    print(f"총 수입: {summary.total_income}원")
    print(f"총 지출: {summary.total_expense}원")
    print(f"잔액: {summary.balance}원")
    if summary.budget is not None:
        print(f"예산: {summary.budget}원 (사용률 {summary.usage_pct}%)")
        if summary.over_budget:
            print(f"[경고] 예산을 {summary.total_expense - summary.budget}원 초과했습니다.")
    if summary.top_categories:
        print()
        print(f"지출 TOP {args.top}")
        for i, (category, amount) in enumerate(summary.top_categories, start=1):
            print(f"{i}) {category} {amount}원")
    return 0


@handle_errors
@log_execution
def cmd_budget_set(args: argparse.Namespace) -> int:
    _, _, budget_service = build_context(args.data_dir)
    amount = budget_service.set_budget(args.month, args.amount)
    print(f"[저장 완료] {args.month} 예산 {amount}원")
    return 0


@handle_errors
@log_execution
def cmd_category_add(args: argparse.Namespace) -> int:
    categories, _, _ = build_context(args.data_dir)
    name = args.name or prompt("카테고리명")
    categories.add(name)
    print(f"[저장 완료] category={name}")
    return 0


@handle_errors
def cmd_category_list(args: argparse.Namespace) -> int:
    categories, _, _ = build_context(args.data_dir)
    for name in categories.list():
        print(f"- {name}")
    return 0


@handle_errors
@log_execution
def cmd_category_remove(args: argparse.Namespace) -> int:
    categories, _, _ = build_context(args.data_dir)
    categories.remove(args.name)
    print(f"[삭제 완료] category={args.name}")
    return 0


@handle_errors
@log_execution
def cmd_update(args: argparse.Namespace) -> int:
    _, transactions, _ = build_context(args.data_dir)
    txn = transactions.update(
        args.id,
        date=args.date,
        type_=args.type,
        category=args.category,
        amount=args.amount,
        memo=args.memo,
        tags=args.tags,
    )
    print("[수정 완료]")
    print(format_transactions([txn]))
    return 0


@handle_errors
@log_execution
def cmd_delete(args: argparse.Namespace) -> int:
    _, transactions, _ = build_context(args.data_dir)
    transactions.delete(args.id)
    print(f"[삭제 완료] id={args.id}")
    return 0


@handle_errors
@log_execution
def cmd_export(args: argparse.Namespace) -> int:
    _, transactions, _ = build_context(args.data_dir)
    if not args.month and not (args.from_ and args.to):
        raise ValidationError(
            "export는 --month 또는 --from/--to 중 하나 이상이 필요합니다.",
            hint="예: export --out export.csv --month 2024-01",
        )
    date_from = args.from_
    date_to = args.to
    if args.month:
        month_first, month_last = month_range(args.month)
        date_from = date_from or month_first
        date_to = date_to or month_last
    filt = SearchFilter(date_from=date_from, date_to=date_to)
    count = export_csv(transactions, Path(args.out), filt)
    print(f"[완료] {args.out} ({count} records)")
    return 0


@handle_errors
@log_execution
def cmd_import(args: argparse.Namespace) -> int:
    _, transactions, _ = build_context(args.data_dir)
    imported, skipped = import_csv(transactions, Path(args.from_))
    print(f"[완료] imported={imported}, skipped={skipped}")
    return 0


@handle_errors
def cmd_backup(args: argparse.Namespace) -> int:
    data_path = Path(args.data_dir)
    if not data_path.exists():
        raise ValidationError(f"데이터 폴더가 없습니다: {data_path}")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = data_path.parent / f"{data_path.name}-backup-{timestamp}"
    shutil.copytree(data_path, backup_dir)
    print(f"[완료] 백업 생성: {backup_dir}")
    return 0


@handle_errors
@log_execution
def cmd_recurring_add(args: argparse.Namespace) -> int:
    service = build_recurring(args.data_dir)
    rule = service.add(args.type, args.day, args.category, args.amount, args.memo, args.tags)
    print(f"[저장 완료] 반복 내역 id={rule.id} (매월 {rule.day}일 {rule.category} {rule.amount}원)")
    return 0


@handle_errors
def cmd_recurring_list(args: argparse.Namespace) -> int:
    rules = build_recurring(args.data_dir).list()
    print(format_recurring(rules) if rules else "[정보] 등록된 반복 내역이 없습니다.")
    return 0


@handle_errors
@log_execution
def cmd_recurring_remove(args: argparse.Namespace) -> int:
    build_recurring(args.data_dir).remove(args.id)
    print(f"[삭제 완료] 반복 내역 id={args.id}")
    return 0


@handle_errors
@log_execution
def cmd_recurring_apply(args: argparse.Namespace) -> int:
    created, skipped = build_recurring(args.data_dir).apply(args.month)
    for txn in created:
        print(f"[생성] {txn.id} {txn.date} {txn.category} {txn.amount}원")
    print(f"[완료] {args.month} created={len(created)}, skipped(이미 적용)={skipped}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="budget_app", description="콘솔 가계부")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="데이터 저장 폴더 (기본: ./data)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="거래 추가 (대화형)")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="거래 목록 (최신순)")
    p_list.add_argument("--limit", type=int, default=10, help="출력할 최대 건수 (기본: 10)")
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="조건 검색")
    p_search.add_argument("--from", dest="from_", help="시작일 YYYY-MM-DD (포함)")
    p_search.add_argument("--to", help="종료일 YYYY-MM-DD (포함)")
    p_search.add_argument("--category", help="카테고리 일치")
    p_search.add_argument("--type", help="income/expense")
    p_search.add_argument("--q", help="메모 키워드 (대소문자 무시)")
    p_search.add_argument("--tag", help="태그 일치")
    p_search.set_defaults(func=cmd_search)

    p_summary = sub.add_parser("summary", help="월별 요약")
    p_summary.add_argument("--month", required=True, help="YYYY-MM")
    p_summary.add_argument("--top", type=int, default=3, help="지출 TOP N 카테고리 (기본: 3)")
    p_summary.set_defaults(func=cmd_summary)

    p_budget = sub.add_parser("budget", help="예산 설정")
    budget_sub = p_budget.add_subparsers(dest="budget_command", required=True)
    p_budget_set = budget_sub.add_parser("set")
    p_budget_set.add_argument("--month", required=True, help="YYYY-MM")
    p_budget_set.add_argument("--amount", required=True, help="양수 정수")
    p_budget_set.set_defaults(func=cmd_budget_set)

    p_category = sub.add_parser("category", help="카테고리 관리")
    category_sub = p_category.add_subparsers(dest="category_command", required=True)
    p_cat_add = category_sub.add_parser("add")
    p_cat_add.add_argument("name", nargs="?", help="생략하면 대화형으로 입력")
    p_cat_add.set_defaults(func=cmd_category_add)
    p_cat_list = category_sub.add_parser("list")
    p_cat_list.set_defaults(func=cmd_category_list)
    p_cat_remove = category_sub.add_parser("remove")
    p_cat_remove.add_argument("name", help="삭제할 카테고리 (사용 중이면 거부)")
    p_cat_remove.set_defaults(func=cmd_category_remove)

    # update is fixed to OPTION-BASED mode (Option A in the spec), not interactive.
    p_update = sub.add_parser("update", help="거래 수정 (옵션 기반)")
    p_update.add_argument("--id", required=True, help="수정할 거래 id (예: TX-000001)")
    p_update.add_argument("--date", help="YYYY-MM-DD")
    p_update.add_argument("--type", help="income/expense")
    p_update.add_argument("--category", help="등록된 카테고리")
    p_update.add_argument("--amount", help="양수 정수")
    p_update.add_argument("--memo", help="메모 (빈 문자열이면 비움)")
    p_update.add_argument("--tags", help="쉼표 구분 태그 (전체 교체)")
    p_update.set_defaults(func=cmd_update)

    p_delete = sub.add_parser("delete", help="거래 삭제")
    p_delete.add_argument("--id", required=True, help="삭제할 거래 id")
    p_delete.set_defaults(func=cmd_delete)

    p_export = sub.add_parser("export", help="CSV 내보내기")
    p_export.add_argument("--out", required=True, help="저장할 CSV 경로")
    p_export.add_argument("--month", help="YYYY-MM (또는 --from/--to)")
    p_export.add_argument("--from", dest="from_", help="시작일 YYYY-MM-DD")
    p_export.add_argument("--to", help="종료일 YYYY-MM-DD")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="CSV 가져오기")
    p_import.add_argument("--from", dest="from_", required=True, help="가져올 CSV 경로 (UTF-8, 헤더 포함)")
    p_import.set_defaults(func=cmd_import)

    p_backup = sub.add_parser("backup", help="[보너스] 데이터 폴더 백업")
    p_backup.set_defaults(func=cmd_backup)

    p_rec = sub.add_parser("recurring", help="[보너스] 반복 내역 (월급/월세 등)")
    rec_sub = p_rec.add_subparsers(dest="recurring_command", required=True)
    p_rec_add = rec_sub.add_parser("add", help="반복 내역 등록")
    p_rec_add.add_argument("--type", required=True, help="income/expense")
    p_rec_add.add_argument("--day", required=True, help="매월 생성일 (1~31, 말일 초과 시 말일)")
    p_rec_add.add_argument("--category", required=True)
    p_rec_add.add_argument("--amount", required=True)
    p_rec_add.add_argument("--memo", default="")
    p_rec_add.add_argument("--tags", default="")
    p_rec_add.set_defaults(func=cmd_recurring_add)
    p_rec_list = rec_sub.add_parser("list", help="반복 내역 목록")
    p_rec_list.set_defaults(func=cmd_recurring_list)
    p_rec_remove = rec_sub.add_parser("remove", help="반복 내역 삭제")
    p_rec_remove.add_argument("--id", required=True)
    p_rec_remove.set_defaults(func=cmd_recurring_remove)
    p_rec_apply = rec_sub.add_parser("apply", help="해당 월 거래 자동 생성 (중복 생성 안 함)")
    p_rec_apply.add_argument("--month", required=True, help="YYYY-MM")
    p_rec_apply.set_defaults(func=cmd_recurring_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
