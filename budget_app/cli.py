"""Command-line interface: argument parsing + interactive prompts only.

No business rules live here - every command delegates validation and
persistence to services.py / storage.py.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .csv_io import export_csv, import_csv
from .decorators import handle_errors, log_execution, measure_time
from .exceptions import AppError, ValidationError
from .models import Transaction
from .services import (
    BudgetService,
    CategoryService,
    SearchFilter,
    TransactionService,
    validate_amount,
)
from .storage import BudgetStore, CategoryStore, TransactionRepository

DEFAULT_DATA_DIR = "./data"


def prompt(label: str, validator=None, default: str | None = None):
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


def format_txn(txn: Transaction) -> str:
    memo = txn.memo or ""
    return f"{txn.id} | {txn.date} | {txn.type:<7} | {txn.category} | {txn.amount} | {memo}"


def build_context(data_dir: str):
    data_path = Path(data_dir)
    categories = CategoryStore(data_path)
    transactions = TransactionRepository(data_path)
    budgets = BudgetStore(data_path)
    category_service = CategoryService(categories, transactions)
    transaction_service = TransactionService(transactions, category_service)
    budget_service = BudgetService(budgets, transactions)
    return category_service, transaction_service, budget_service


@handle_errors
@log_execution
@measure_time
def cmd_add(args: argparse.Namespace) -> int:
    categories, transactions, _ = build_context(args.data_dir)
    print("사용 가능한 카테고리:", ", ".join(categories.list()))
    date = prompt("날짜(YYYY-MM-DD)", lambda v: v)
    type_ = prompt("타입(income/expense)", lambda v: v)
    category = prompt("카테고리", lambda v: v)
    amount = prompt("금액(양수)", lambda v: v)
    memo = prompt("메모(선택)", default="")
    tags = prompt("태그(쉼표로 구분, 없으면 엔터)", default="")

    # validate/re-prompt loop so a single bad field doesn't restart the whole form
    while True:
        try:
            txn = transactions.add(date, type_, category, amount, memo, tags)
            break
        except ValidationError as exc:
            print(f"[오류] {exc.message}")
            if exc.hint:
                print(f"[힌트] {exc.hint}")
            if "날짜" in exc.message:
                date = prompt("날짜(YYYY-MM-DD)", lambda v: v)
            elif "type" in exc.message.lower():
                type_ = prompt("타입(income/expense)", lambda v: v)
            elif "카테고리" in exc.message:
                category = prompt("카테고리", lambda v: v)
            else:
                amount = prompt("금액(양수)", lambda v: v)

    print(f"[저장 완료] id={txn.id}")
    return 0


@handle_errors
@log_execution
def cmd_list(args: argparse.Namespace) -> int:
    _, transactions, _ = build_context(args.data_dir)
    count = 0
    for txn in transactions.list_latest(limit=args.limit):
        print(format_txn(txn))
        count += 1
    if count == 0:
        print("[정보] 거래 내역이 없습니다.")
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
    count = 0
    for txn in transactions.search(filt):
        print(format_txn(txn))
        count += 1
    if count == 0:
        print("[정보] 조건에 맞는 거래가 없습니다.")
    return 0


@handle_errors
@log_execution
def cmd_summary(args: argparse.Namespace) -> int:
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
            print("[경고] 예산을 초과했습니다.")
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
    print(f"[수정 완료] {format_txn(txn)}")
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
        date_from = date_from or f"{args.month}-01"
        date_to = date_to or f"{args.month}-31"
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="budget_app", description="콘솔 가계부")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="데이터 저장 폴더 (기본: ./data)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="거래 추가 (대화형)")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="거래 목록 (최신순)")
    p_list.add_argument("--limit", type=int, default=10)
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="조건 검색")
    p_search.add_argument("--from", dest="from_")
    p_search.add_argument("--to")
    p_search.add_argument("--category")
    p_search.add_argument("--type")
    p_search.add_argument("--q")
    p_search.add_argument("--tag")
    p_search.set_defaults(func=cmd_search)

    p_summary = sub.add_parser("summary", help="월별 요약")
    p_summary.add_argument("--month", required=True)
    p_summary.add_argument("--top", type=int, default=3)
    p_summary.set_defaults(func=cmd_summary)

    p_budget = sub.add_parser("budget", help="예산 설정")
    budget_sub = p_budget.add_subparsers(dest="budget_command", required=True)
    p_budget_set = budget_sub.add_parser("set")
    p_budget_set.add_argument("--month", required=True)
    p_budget_set.add_argument("--amount", required=True)
    p_budget_set.set_defaults(func=cmd_budget_set)

    p_category = sub.add_parser("category", help="카테고리 관리")
    category_sub = p_category.add_subparsers(dest="category_command", required=True)
    p_cat_add = category_sub.add_parser("add")
    p_cat_add.add_argument("name", nargs="?")
    p_cat_add.set_defaults(func=cmd_category_add)
    p_cat_list = category_sub.add_parser("list")
    p_cat_list.set_defaults(func=cmd_category_list)
    p_cat_remove = category_sub.add_parser("remove")
    p_cat_remove.add_argument("name")
    p_cat_remove.set_defaults(func=cmd_category_remove)

    # update is fixed to OPTION-BASED mode (Option A in the spec), not interactive.
    p_update = sub.add_parser("update", help="거래 수정 (옵션 기반)")
    p_update.add_argument("--id", required=True)
    p_update.add_argument("--date")
    p_update.add_argument("--type")
    p_update.add_argument("--category")
    p_update.add_argument("--amount")
    p_update.add_argument("--memo")
    p_update.add_argument("--tags")
    p_update.set_defaults(func=cmd_update)

    p_delete = sub.add_parser("delete", help="거래 삭제")
    p_delete.add_argument("--id", required=True)
    p_delete.set_defaults(func=cmd_delete)

    p_export = sub.add_parser("export", help="CSV 내보내기")
    p_export.add_argument("--out", required=True)
    p_export.add_argument("--month")
    p_export.add_argument("--from", dest="from_")
    p_export.add_argument("--to")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="CSV 가져오기")
    p_import.add_argument("--from", dest="from_", required=True)
    p_import.set_defaults(func=cmd_import)

    p_backup = sub.add_parser("backup", help="[보너스] 데이터 폴더 백업")
    p_backup.set_defaults(func=cmd_backup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
