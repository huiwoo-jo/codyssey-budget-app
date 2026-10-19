"""End-to-end checks through the real CLI entry point (stdlib unittest only).

Run: python3 -m unittest -v
"""
from __future__ import annotations

import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from budget_app.cli import main
from budget_app.formatters import display_width, format_table


class CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.data = self.tmp / "data"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_cli(self, *argv: str, inputs: list[str] | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch(
            "builtins.input", side_effect=list(inputs or [])
        ):
            code = main(["--data-dir", str(self.data), *argv])
        return code, out.getvalue(), err.getvalue()

    def add(self, date: str, type_: str, category: str, amount: str, memo: str = "", tags: str = "") -> str:
        code, out, _ = self.run_cli("add", inputs=[date, type_, category, amount, memo, tags])
        self.assertEqual(code, 0, out)
        return out.strip().split("id=")[-1]

    # --- required features -------------------------------------------------

    def test_three_storage_files_and_default_categories(self) -> None:
        self.add("2024-01-15", "expense", "food", "15000", "점심", "meal")
        self.run_cli("budget", "set", "--month", "2024-01", "--amount", "500000")
        for name in ("transactions.jsonl", "categories.jsonl", "budgets.jsonl"):
            self.assertTrue((self.data / name).exists(), name)
        _, out, _ = self.run_cli("category", "list")
        self.assertIn("- food", out)

    def test_add_reprompts_only_the_invalid_field(self) -> None:
        code, out, _ = self.run_cli(
            "add", inputs=["2024-13-40", "2024-01-15", "spend", "expense", "nope", "food", "-5", "15000", "", ""]
        )
        self.assertEqual(code, 0)
        self.assertIn("날짜 형식이 올바르지 않습니다", out)
        self.assertIn("type은", out)
        self.assertIn("등록되지 않은 카테고리", out)
        self.assertIn("양수", out)
        self.assertIn("[저장 완료] id=TX-000001", out)

    def test_list_newest_first_with_limit(self) -> None:
        for day in ("10", "11", "12"):
            self.add(f"2024-01-{day}", "expense", "food", "1000")
        _, out, _ = self.run_cli("list", "--limit", "2")
        self.assertIn("TX-000003", out)
        self.assertIn("TX-000002", out)
        self.assertNotIn("TX-000001", out)
        self.assertLess(out.index("TX-000003"), out.index("TX-000002"))

    def test_search_filters(self) -> None:
        self.add("2024-01-10", "expense", "food", "1000", "점심 김밥", "meal")
        self.add("2024-01-20", "income", "etc", "5000", "용돈")
        self.add("2024-02-01", "expense", "transport", "1500")
        _, out, _ = self.run_cli("search", "--from", "2024-01-01", "--to", "2024-01-31", "--type", "expense")
        self.assertIn("TX-000001", out)
        self.assertNotIn("TX-000002", out)
        self.assertNotIn("TX-000003", out)
        _, out, _ = self.run_cli("search", "--q", "김밥", "--tag", "meal")
        self.assertIn("TX-000001", out)

    def test_summary_budget_warning_and_empty_month(self) -> None:
        self.add("2024-01-01", "income", "etc", "3000000")
        self.add("2024-01-05", "expense", "rent", "450000")
        self.add("2024-01-06", "expense", "food", "100000")
        self.run_cli("budget", "set", "--month", "2024-01", "--amount", "500000")
        _, out, _ = self.run_cli("summary", "--month", "2024-01", "--top", "1")
        self.assertIn("총 수입: 3000000원", out)
        self.assertIn("잔액: 2450000원", out)
        self.assertIn("사용률 110.0%", out)
        self.assertIn("[경고]", out)
        self.assertIn("1) rent 450000원", out)
        self.assertNotIn("2)", out)
        _, out, _ = self.run_cli("summary", "--month", "2023-12")
        self.assertIn("데이터 없음", out)

    def test_update_delete_and_missing_id(self) -> None:
        txn_id = self.add("2024-01-15", "expense", "food", "15000")
        code, out, _ = self.run_cli("update", "--id", txn_id, "--amount", "16000", "--memo", "저녁")
        self.assertEqual(code, 0)
        self.assertIn("16,000", out)
        self.assertEqual(self.run_cli("delete", "--id", txn_id)[0], 0)
        code, _, err = self.run_cli("delete", "--id", txn_id)
        self.assertNotEqual(code, 0)
        self.assertIn("찾을 수 없습니다", err)
        self.assertNotIn("Traceback", err)

    def test_category_in_use_cannot_be_removed(self) -> None:
        self.add("2024-01-15", "expense", "food", "15000")
        code, _, err = self.run_cli("category", "remove", "food")
        self.assertNotEqual(code, 0)
        self.assertIn("[힌트]", err)
        self.assertEqual(self.run_cli("category", "remove", "rent")[0], 0)

    def test_export_import_roundtrip(self) -> None:
        self.add("2024-02-28", "expense", "food", "1000", "메모, 쉼표", "a,b")
        self.add("2024-03-01", "expense", "food", "2000")
        out_csv = self.tmp / "out.csv"
        code, out, _ = self.run_cli("export", "--out", str(out_csv), "--month", "2024-02")
        self.assertEqual(code, 0)
        self.assertIn("(1 records)", out)
        with out_csv.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["tags"], "a,b")
        self.assertEqual(list(rows[0]), ["date", "type", "category", "amount", "memo", "tags"])

        with out_csv.open("a", encoding="utf-8") as f:
            f.write("2024-02-30,expense,food,100,,\n")  # invalid date -> skipped
        _, out, _ = self.run_cli("import", "--from", str(out_csv))
        self.assertIn("imported=1, skipped=1", out)

    def test_export_requires_condition(self) -> None:
        code, _, err = self.run_cli("export", "--out", str(self.tmp / "x.csv"))
        self.assertNotEqual(code, 0)
        self.assertIn("--month", err)

    # --- regressions -------------------------------------------------------

    def test_non_padded_date_is_rejected(self) -> None:
        code, _, err = self.run_cli("search", "--from", "2024-1-5")
        self.assertNotEqual(code, 0)
        self.assertIn("날짜 형식", err)

    def test_deleted_id_is_never_reused(self) -> None:
        self.add("2024-01-01", "expense", "food", "1")
        last = self.add("2024-01-02", "expense", "food", "1")
        self.run_cli("delete", "--id", last)
        self.assertEqual(self.add("2024-01-03", "expense", "food", "1"), "TX-000003")

    def test_invalid_options_fail_cleanly(self) -> None:
        for argv in (("list", "--limit", "0"), ("search", "--type", "xx"), ("summary", "--month", "2024-13")):
            code, _, err = self.run_cli(*argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn("[오류]", err)

    def test_eof_during_interactive_input(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()), mock.patch(
            "builtins.input", side_effect=EOFError
        ):
            code = main(["--data-dir", str(self.data), "add"])
        self.assertEqual(code, 1)
        self.assertIn("입력이 끝나", err.getvalue())

    # --- bonus -------------------------------------------------------------

    def test_backup_creates_timestamped_copy(self) -> None:
        self.add("2024-01-01", "expense", "food", "1")
        code, _, _ = self.run_cli("backup")
        self.assertEqual(code, 0)
        backups = list(self.tmp.glob("data-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "transactions.jsonl").exists())

    def test_recurring_apply_clamps_day_and_is_idempotent(self) -> None:
        self.run_cli("category", "add", "salary")
        self.run_cli("recurring", "add", "--type", "income", "--day", "31", "--category", "salary", "--amount", "3000000")
        _, out, _ = self.run_cli("recurring", "apply", "--month", "2024-02")
        self.assertIn("2024-02-29", out)  # leap-year month end
        self.assertIn("created=1", out)
        _, out, _ = self.run_cli("recurring", "apply", "--month", "2024-02")
        self.assertIn("created=0, skipped(이미 적용)=1", out)
        code, _, _ = self.run_cli("category", "remove", "salary")
        self.assertNotEqual(code, 0)

    def test_atomic_rewrite_leaves_no_tmp_file(self) -> None:
        txn_id = self.add("2024-01-01", "expense", "food", "1")
        self.run_cli("update", "--id", txn_id, "--amount", "2")
        self.assertEqual(list(self.data.glob("*.tmp")), [])

    def test_failed_delete_keeps_original_and_no_tmp(self) -> None:
        self.add("2024-01-01", "expense", "food", "1")
        before = (self.data / "transactions.jsonl").read_bytes()
        code, _, _ = self.run_cli("delete", "--id", "TX-404")
        self.assertNotEqual(code, 0)
        self.assertEqual((self.data / "transactions.jsonl").read_bytes(), before)
        self.assertEqual(list(self.data.glob("*.tmp")), [])

    def test_table_aligns_korean(self) -> None:
        table = format_table(("메모", "x"), [["점심", "1"], ["abcd", "2"]])
        widths = {display_width(line.split("|")[0]) for line in table.splitlines() if "|" in line}
        self.assertEqual(len(widths), 1, table)


if __name__ == "__main__":
    unittest.main()
