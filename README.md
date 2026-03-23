# Argus

> I keep watching so you don't have to.

Argus는 데이터 파이프라인 오류를 자동으로 감지·분류하고,
LLM을 활용해 원인과 확인 포인트를 요약해서 팀에게 전달하는 오픈소스 모니터링 도구입니다.

---

## 핵심 가치

오류가 발생했을 때 사람이 30분 걸려 파악할 내용을 **3분 안에 요약**합니다.
자동 수정이 목표가 아닙니다. **빠른 컨텍스트 제공**이 목표입니다.

---

## 빠른 시작

```bash
pip install git+https://github.com/binnini/argus-pipeline.git
```

```python
import argus
from argus import IngestionLayer, TransformLayer, LoadLayer

argus.init(
    slack_webhook="https://hooks.slack.com/...",
    anthropic_api_key="sk-ant-...",
)

ingestion = IngestionLayer(source_type="postgres")
transform = TransformLayer()
load      = LoadLayer(target="bigquery://project/dataset/table")

@ingestion.watch
def fetch(conn):
    df = pd.read_sql(query, conn)
    ingestion.track(row_count=len(df))
    return df

@transform.watch
def clean(df):
    transform.snapshot(df, "before")
    df = df.dropna(subset=["user_id"])
    transform.snapshot(df, "after")
    return df

@load.watch
def write(df, client):
    job = client.load_table(df, TABLE)
    load.verify(expected=len(df), loaded=job.output_rows)
```

오류가 발생하면 Slack에 자동으로 요약이 전송됩니다.

---

## 아키텍처

```
파이프라인 (@watch 데코레이터)
        ↓ 예외 발생 — try/except로 즉시 캡처
Event collector  — 표준 스키마로 정규화
        ↓
Rule classifier  — custom rules → built-in rules 순으로 분류 (무료, 70-80% 처리)
        ↓ 복잡 케이스만
Context builder  — 메타데이터·메트릭만 추출, ~500 tokens
        ↓
LLM (Claude)     — 원인 요약 + 확인 포인트
        ↓
Slack + Dashboard
```

### 하이브리드 모니터링 (dbt 등)

`@watch` 데코레이터(try/except)만으로 잡기 어려운 스택별 오류는 `LogAnalyzer`를 함께 사용합니다.

```python
import subprocess
from argus import TransformLayer
from argus.sdk.analyzers import DbtLogAnalyzer

transform = TransformLayer(analyzer=DbtLogAnalyzer("./transform"))

@transform.watch
def run_dbt():
    # 실패 시 DbtLogAnalyzer가 run_results.json에서
    # 실제 SQL 오류 메시지를 추출해 classifier에 전달
    subprocess.run(["dbt", "run"], check=True)
```

---

## 오류 분류

### Built-in 규칙 (10개)

| 유형 | 감지 조건 | LLM 호출 |
|------|-----------|----------|
| `connection_timeout` | timeout 키워드 | 없음 |
| `oom` | MemoryError | 없음 |
| `disk_full` | no space left | 없음 |
| `schema_change` | column does not exist, KeyError | 있음 |
| `type_mismatch` | datatype mismatch, TypeError | 있음 |
| `null_spike` | null_rate_delta > 20% | 있음 |
| `volume_drop` | row_count_delta < -30% | 있음 |
| `data_loss` | loss_rate > 1% | 있음 |
| `source_unavailable` | 401 / 403 / 404 | 없음 |
| `rate_limit` | 429, too many requests | 없음 |

### 사용자 정의 규칙 (CustomRule)

스택 특화 패턴이나 프로젝트별 assertion 메시지는 정규표현식으로 주입합니다.
Custom rules는 built-in rules보다 먼저 실행됩니다.

```python
from argus import CustomRule

argus.init(
    custom_rules=[
        CustomRule(
            pattern=r"row count too low|expected ~?[\d,]+ got [\d,]+",
            error_type="volume_drop",
            severity="warning",
            needs_llm=True,
        ),
    ]
)
```

### 스택별 Built-in 규칙 (dbt)

```python
from argus.rules.dbt import DBT_RULES

argus.init(custom_rules=DBT_RULES)
```

| 유형 | 감지 조건 |
|------|-----------|
| `dbt_compilation_error` | Jinja 오류, undefined variable, ref() 대상 없음 |
| `null_spike` | not_null 테스트 실패 |
| `schema_change` | relationships 테스트 실패 |
| `type_mismatch` | accepted_range / accepted_values 테스트 실패 |
| `dbt_duplicate_key` | unique 테스트 실패 |
| `dbt_source_freshness` | source freshness 초과 |
| `dbt_runtime_error` | 모델 실행 실패 (위 규칙에 매칭 안 된 경우) |

### 커스텀 스택 규칙 조합

```python
from argus.rules.dbt import DBT_RULES
from argus import CustomRule

argus.init(
    custom_rules=DBT_RULES + [
        CustomRule(pattern=r"my pattern", error_type="my_error", needs_llm=True),
    ]
)
```

---

## LogAnalyzer — 로그/아티팩트 기반 메트릭 보완

`@watch`가 잡은 예외에 스택별 로그에서 추출한 메트릭을 자동으로 병합합니다.

```python
from argus.sdk.analyzers import DbtLogAnalyzer

transform = TransformLayer(analyzer=DbtLogAnalyzer("./transform"))
```

`DbtLogAnalyzer`는 `target/run_results.json`을 파싱합니다:
- **오류 시**: `CalledProcessError` 대신 실제 SQL 오류 메시지 추출 → classifier 정확도 향상
- **성공 시**: `models_run`, `rows_affected`, `execution_time_sec`, `model_statuses` 메트릭 자동 기록

새 스택 추가 시 `LogAnalyzer` ABC를 구현합니다:

```python
from argus.sdk.analyzers.base import LogAnalyzer

class AirflowLogAnalyzer(LogAnalyzer):
    def extract_metrics(self) -> dict: ...
    def extract_error(self) -> str | None: ...
```

---

## 토큰 절감 추적

- **기준값**: 사람이 로그를 LLM CLI에 직접 붙여넣을 때 평균 8,000 tokens
- **실제**: 규칙 처리 + 압축 컨텍스트로 평균 ~1,200 tokens
- **대시보드**: 오늘/누적 절감 토큰과 절감 비용을 실시간 표시

---

## 대시보드

```bash
uvicorn argus.outputs.dashboard.app:app --port 7070
```

`http://localhost:7070` 에서 확인.

---

## 테스트

```bash
pip install -e ".[dev]"
pytest
```

LLM API 키 없이도 stub 모드로 전체 테스트 통과합니다.

---

## 프로젝트 구조

```
argus/
├── sdk/
│   ├── base.py              # @watch 데코레이터, 이벤트 빌더
│   ├── emitter.py           # 이벤트 전송 (local / http)
│   ├── agent.py             # argus.init(), sys.excepthook
│   ├── layers/
│   │   ├── ingestion.py     # IngestionLayer
│   │   ├── transform.py     # TransformLayer
│   │   └── load.py          # LoadLayer
│   └── analyzers/
│       ├── base.py          # LogAnalyzer ABC
│       └── dbt.py           # DbtLogAnalyzer (run_results.json)
├── engine/
│   ├── classifier.py        # 규칙 기반 분류 + CustomRule
│   ├── context.py           # 프롬프트 빌더 (~500 tokens)
│   ├── llm.py               # Anthropic 호출 + 토큰 추적
│   └── pipeline.py          # EnginePipeline 싱글턴
├── rules/
│   └── dbt.py               # DBT_RULES (7개 dbt 특화 규칙)
├── storage/
│   └── sqlite.py            # 오류 히스토리, token_usage 테이블
└── outputs/
    ├── slack.py             # Slack 웹훅 알림
    └── dashboard/
        └── app.py           # FastAPI 대시보드
```

---

## 라이선스

MIT
