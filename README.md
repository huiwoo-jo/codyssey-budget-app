# codyssey-budget-app

콘솔 기반 개인 가계부(용돈 기입장) 프로그램. 표준 라이브러리만 사용하며,
파일 3종(JSONL)에 데이터를 영구 저장합니다.

## 실행 방법

Python 3.10 이상이 필요합니다. 외부 의존성은 없습니다.

```bash
python3 -m budget_app <command> [options]
python3 -m budget_app --help
```

## 저장 파일 위치/형식

기본 저장 폴더는 `./data` (옵션 `--data-dir`로 변경 가능) 이며, JSONL(한 줄에
JSON 객체 하나) 형식으로 3개 파일에 나누어 저장합니다.

| 파일 | 내용 |
| --- | --- |
| `data/transactions.jsonl` | 거래 내역 |
| `data/categories.jsonl` | 카테고리 목록 (최초 실행 시 food/transport/rent/etc 자동 생성) |
| `data/budgets.jsonl` | 월별 예산 |

`update`/`delete`는 임시 파일에 전체를 다시 써서 `os.replace`로 원자적으로
교체합니다 (중간에 프로세스가 죽어도 파일이 깨지지 않습니다). `list`/`search`는
파일을 통째로 메모리에 올리지 않고, 파일을 뒤에서부터 청크 단위로 읽는
제너레이터(`storage.iter_reverse`)로 최신순 스트리밍 처리합니다.

## 구조

```
budget_app/
  models.py      Transaction dataclass
  storage.py      JSONL 저장소 (TransactionRepository/CategoryStore/BudgetStore)
  services.py      검증 + 비즈니스 로직 (TransactionService/CategoryService/BudgetService)
  csv_io.py        CSV import/export
  decorators.py     handle_errors / log_execution / measure_time
  cli.py          argparse 커맨드 정의 (대화형 입력 포함)
```

## 주요 명령 예시

```bash
# 거래 추가 (대화형)
python3 -m budget_app add

# 최근 3건 조회
python3 -m budget_app list --limit 3

# 검색
python3 -m budget_app search --category food --type expense --from 2024-01-01 --to 2024-01-31

# 월별 요약 + 카테고리 TOP N
python3 -m budget_app summary --month 2024-01 --top 3

# 예산 설정
python3 -m budget_app budget set --month 2024-01 --amount 500000

# 카테고리 관리
python3 -m budget_app category add
python3 -m budget_app category list
python3 -m budget_app category remove food   # 사용 중이면 삭제 거부

# 수정(옵션 기반으로 고정, 대화형 아님) / 삭제
python3 -m budget_app update --id TX-000001 --amount 16000
python3 -m budget_app delete --id TX-000001

# CSV 내보내기/가져오기
python3 -m budget_app export --out export.csv --month 2024-01
python3 -m budget_app import --from export.csv

# [보너스] 데이터 폴더 백업 (타임스탬프 포함)
python3 -m budget_app backup
```

### `update` 방식 고정

과제 요구사항에 따라 `update`는 **옵션 인자 방식(안 A)** 으로 고정했습니다.
`update --id <id> [--date] [--type] [--category] [--amount] [--memo] [--tags]`
형태로, 지정한 필드만 변경됩니다.

## import/export CSV 스키마

UTF-8, 헤더 포함, 컬럼명 고정:

| column | required | 설명 |
| --- | --- | --- |
| date | Y | YYYY-MM-DD |
| type | Y | income / expense |
| category | Y | 등록된 카테고리 |
| amount | Y | 양수 정수 |
| memo | N | 문자열 |
| tags | N | 쉼표(,) 구분 문자열 |

## 오류 처리

모든 오류는 스택트레이스 대신 `[오류] 원인` + `[힌트] 해결 방법` 형태로
출력되며, 정상 종료는 exit code 0, 오류 종료는 0이 아닌 값입니다.

## 제약 사항 준수

- 표준 라이브러리만 사용 (외부 pip 패키지 없음)
- 저장 포맷: JSONL, 파일 3개 이상으로 분리
- 옵션 표기: `--` 통일
