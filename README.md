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

> PyPI 배포 전 단계입니다. 아래 방법으로 설치합니다.

```bash
pip install git+https://github.com/binnini/argus-pipeline.git

# 프로젝트 초기화 — argus.toml + .env 생성
argus init
```

엔트리포인트 스크립트에 한 번만 추가합니다. 나머지 스크립트는 수정 불필요.

```python
import argus
from argus import IngestionLayer, TransformLayer, LoadLayer

argus.init()  # argus.toml + 환경 변수 자동 읽기

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

## 설정

### argus init

프로젝트 루트에서 한 번 실행하면 `argus.toml`과 `.env`를 생성합니다.

```bash
argus init            # argus.toml + .env 생성 (없는 키만 추가)
argus init --force    # argus.toml 덮어쓰기 (.env는 항상 안전하게 이어쓰기)
```

### argus.toml — 동작 설정 (버전 관리 O)

LLM 백엔드, custom rules 등 동작 설정을 관리합니다.
cwd에서 시작해 루트 디렉토리까지 자동으로 탐색하므로 프로젝트 루트에 하나만 두면 됩니다.

```toml
[llm]
backend = "anthropic"   # "anthropic" | "ollama"
# backend = "ollama"
# ollama_url = "http://localhost:11434"
# ollama_model = "llama3.2"

[storage]
db_path = "argus.db"

# 프로젝트 공통 custom rules
[[rules]]
pattern = 'row count too low|expected ~?[\d,]+ got [\d,]+'
error_type = "volume_drop"
severity = "warning"
description = "Source row count dropped significantly vs baseline"
needs_llm = true
```

### .env — 비밀값 (버전 관리 X)

API 키와 Webhook URL만 관리합니다.

```bash
# Anthropic 사용 시
ANTHROPIC_API_KEY=sk-ant-...

# Slack 알림 (선택)
SLACK_WEBHOOK=https://hooks.slack.com/services/...
```

### 설정 우선순위

`init()` 명시적 파라미터 > 환경 변수 > `argus.toml` > 기본값

### LLM 백엔드

**Anthropic Claude** (기본값)

```bash
pip install "argus-pipeline[anthropic]"
```

```toml
# argus.toml
[llm]
backend = "anthropic"
```

**로컬 Ollama** (비용 $0, 추가 패키지 불필요)

```bash
ollama pull llama3.2
```

```toml
# argus.toml
[llm]
backend = "ollama"
ollama_url = "http://localhost:11434"
ollama_model = "llama3.2"
```

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
LLM              — 원인 요약 + 확인 포인트 (Anthropic 또는 Ollama)
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

**방법 1 — argus.toml** (여러 스크립트에서 공유)

```toml
[[rules]]
pattern = 'row count too low|expected ~?[\d,]+ got [\d,]+'
error_type = "volume_drop"
severity = "warning"
description = "Source row count dropped significantly vs baseline"
needs_llm = true
```

**방법 2 — 코드** (스크립트별 규칙)

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

> 코드로 전달한 `custom_rules`는 `argus.toml`의 rules를 대체합니다.

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

```python
# dbt 규칙 + 프로젝트 규칙 조합
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
- **로컬 LLM**: Ollama 사용 시 API 비용 $0, 절감액은 Anthropic 가격 기준으로 환산 표시
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
├── cli.py               # argus init CLI
├── sdk/
│   ├── base.py          # @watch 데코레이터, 이벤트 빌더
│   ├── emitter.py       # 이벤트 전송 (local / http)
│   ├── agent.py         # argus.init(), argus.toml 로드, sys.excepthook
│   ├── layers/
│   │   ├── ingestion.py # IngestionLayer
│   │   ├── transform.py # TransformLayer
│   │   └── load.py      # LoadLayer
│   └── analyzers/
│       ├── base.py      # LogAnalyzer ABC
│       └── dbt.py       # DbtLogAnalyzer (run_results.json)
├── engine/
│   ├── classifier.py    # 규칙 기반 분류 + CustomRule
│   ├── context.py       # 프롬프트 빌더 (~500 tokens)
│   ├── llm.py           # Anthropic / Ollama 호출 + 토큰 추적
│   └── pipeline.py      # EnginePipeline 싱글턴
├── rules/
│   └── dbt.py           # DBT_RULES (7개 dbt 특화 규칙)
├── storage/
│   └── sqlite.py        # 오류 히스토리, token_usage 테이블
└── outputs/
    ├── slack.py         # Slack 웹훅 알림
    └── dashboard/
        └── app.py       # FastAPI 대시보드
```

---

## 라이선스

MIT
