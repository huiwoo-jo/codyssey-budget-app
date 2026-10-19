# 작업 설명문 - codyssey-budget-app (B2-1)

## 무엇을 만들었는가

Python 표준 라이브러리만으로 동작하는 콘솔 가계부 CLI. 거래
추가/조회/검색/수정/삭제, 월별 요약과 예산 경고, 카테고리 관리,
CSV import/export까지 미션 요구 10개 기능을 모두 구현했다.

## 구조와 설계 결정

- **계층 분리**: `models`(데이터) → `storage`(파일 I/O) →
  `services`(검증/비즈니스 로직) → `cli`(argparse + 대화형 입력).
  CLI는 서비스만 호출하고, 검증 규칙은 `services.py` 한 곳에만 존재한다.
- **저장 포맷**: JSONL 3파일(`transactions`/`categories`/`budgets`) 선택.
  CSV보다 한 줄 = 한 레코드 구조가 append/파싱에 더 단순했다.
- **스트리밍 조회**: `list`/`search`는 파일을 통째로 읽지 않고
  `storage.iter_reverse()`가 파일을 뒤에서부터 8KB 청크로 읽어
  최신순으로 스트리밍한다. `update`/`delete`처럼 전체를 다시 써야 하는
  경우만 임시 파일 + `os.replace`로 원자적 교체한다.
- **데코레이터**: `handle_errors`(스택트레이스 대신 원인+힌트 출력,
  종료 코드 결정) / `log_execution` / `measure_time` 3개를 구현해
  모든 명령 핸들러에 적용했다.
- **update 방식**: 대화형과 옵션 방식 중 옵션 기반(`--id` + 변경할
  필드만 지정)으로 고정했다. 문서(README)에도 명시했다.
- **카테고리 초기값**: 카테고리 파일이 비어 있으면 기본 카테고리
  (food/transport/rent/etc)를 자동 생성하는 안(A)을 선택해 `add`가
  막히지 않도록 했다.

## 요구사항 대비 체크

- [x] add/list/search/summary/budget/category/update/delete/import/export
- [x] 데이터 3파일 이상 영구 저장
- [x] 제너레이터 스트리밍 처리 (list/search)
- [x] 데코레이터 1개 이상 (3개 구현)
- [x] 타입 힌트 적용
- [x] 최소 3개 이상 모듈로 분리 (7개 모듈)
- [x] 오류: 스택트레이스 없이 원인+힌트, 종료 코드 0/비0
- [x] 표준 라이브러리만 사용
- [x] [보너스] backup 명령 구현 (타임스탬프 백업 폴더 생성)
- [x] [보너스] 반복 내역 `recurring add/list/remove/apply` (중복 방지, 말일 보정)
- [x] [보너스] 표 정렬 출력 `formatters.py` (한글 표시 폭 계산)
- [x] [보너스] 저장 원자성 강화 (임시 파일 + fsync + os.replace, 실패 시 임시 파일 정리)

## 2차 검토에서 수정한 사항

- `2024-1-5`처럼 0 패딩 없는 날짜가 통과해 기간 검색이 틀어지던 문제 → 엄격 검증
- 가장 최근 거래 삭제 후 추가 시 삭제된 id가 재발급되던 문제 → `transactions.seq`
- `list --limit 0`, `search --type xx`, `export --month 2024-13` 등이 조용히 통과하던 문제 → 오류 처리
- 입력 스트림 종료(EOF) 시 모호한 메시지 → 명확한 원인/힌트
- `add`의 재입력이 오류 문구 문자열 매칭에 의존하던 구조 → 필드별 검증 함수
- `export --month`가 말일을 `-31`로 가정 → `calendar.monthrange`, 날짜순 정렬
- `update`/`delete`가 파일 전체를 리스트로 로드 → 임시 파일로 스트리밍 재작성
- `unittest` 기반 종단 간 테스트 18개 추가, 기술 설명서(`docs/TECHNICAL.md`) 작성

## 검증

`python3 -m budget_app`으로 add/list/search/summary/budget/category/
update/delete/export/import/backup 전 명령을 수동 실행해 정상 동작과
오류 케이스(없는 id, 잘못된 날짜, 사용 중 카테고리 삭제 시도, export
조건 누락)를 확인했다.
