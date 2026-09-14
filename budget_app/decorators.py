"""Cross-cutting concerns (error handling, logging, timing) kept out of
the command functions themselves, applied via decorators."""
from __future__ import annotations

import functools
import sys
import time
from typing import Callable, TypeVar

from .exceptions import AppError

F = TypeVar("F", bound=Callable[..., int])


def handle_errors(func: F) -> F:
    """Turn AppError into a clean [오류]/[힌트] message and a non-zero exit.

    Never prints a stack trace, per the CLI's error-output contract.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs) or 0
        except AppError as exc:
            print(f"[오류] {exc.message}", file=sys.stderr)
            if exc.hint:
                print(f"[힌트] {exc.hint}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\n[중단] 사용자가 입력을 취소했습니다.", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - last-resort guard, no traceback shown
            print(f"[오류] 예상치 못한 문제가 발생했습니다: {exc}", file=sys.stderr)
            print("[힌트] 입력값과 --data-dir 경로를 확인하세요.", file=sys.stderr)
            return 1

    return wrapper  # type: ignore[return-value]


def log_execution(func: F) -> F:
    """Print a one-line execution log to stderr (command + exit status)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        name = func.__name__
        print(f"[LOG] {name} 실행 시작", file=sys.stderr)
        result = func(*args, **kwargs)
        print(f"[LOG] {name} 실행 종료 (exit={result})", file=sys.stderr)
        return result

    return wrapper  # type: ignore[return-value]


def measure_time(func: F) -> F:
    """Print elapsed wall-clock time for the wrapped command to stderr."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"[TIME] {func.__name__} {elapsed:.3f}s", file=sys.stderr)
        return result

    return wrapper  # type: ignore[return-value]
