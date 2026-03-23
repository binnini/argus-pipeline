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
pip install argus-pipeline
```

```python
import argus

# 전역 초기화 — 이후 모든 예외를 자동 캡처
argus.init(
    slack_webhook="https://hooks.slack.com/...",
    anthropic_api_key="sk-ant-...",
)

# 레이어별 데코레이터
from argus import IngestionLayer, TransformLayer, LoadLayer

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
        ↓ 예외 발생
Event collector  — 표준 스키마로 정규화
        ↓
Rule classifier  — 5개 유형으로 1차 분류 (무료, 70-80% 처리)
        ↓ 복잡 케이스만
Context builder  — 메타데이터·메트릭만 추출, ~500 tokens
        ↓
LLM (Claude)     — 원인 요약 + 확인 포인트
        ↓
Slack + Dashboard
```

---

## 오류 유형

| 유형 | 감지 조건 | LLM 호출 |
|------|-----------|----------|
| `connection_timeout` | timeout 키워드 | 없음 |
| `schema_change` | column does not exist | 있음 |
| `null_spike` | null_rate_delta > 20% | 있음 |
| `volume_drop` | row_count_delta < -30% | 있음 |
| `data_loss` | loss_rate > 1% | 있음 |
| `oom` | MemoryError | 없음 |
| `unknown` | 매칭 없음 | 있음 |

---

## 토큰 절감 추적

Argus는 LLM 호출 비용과 절감량을 자동으로 추적합니다.

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
│   ├── base.py          # @watch 데코레이터, 이벤트 빌더
│   ├── emitter.py       # 이벤트 전송 (local / http)
│   ├── agent.py         # argus.init(), sys.excepthook
│   └── layers/
│       ├── ingestion.py # IngestionLayer
│       ├── transform.py # TransformLayer
│       └── load.py      # LoadLayer
├── engine/
│   ├── classifier.py    # 규칙 기반 분류 (10개 규칙)
│   ├── context.py       # 프롬프트 빌더 (~500 tokens)
│   ├── llm.py           # Anthropic 호출 + 토큰 추적
│   └── pipeline.py      # EnginePipeline 싱글턴
├── storage/
│   └── sqlite.py        # 오류 히스토리, token_usage 테이블
└── outputs/
    ├── slack.py          # Slack 웹훅 알림
    └── dashboard/
        └── app.py        # FastAPI 대시보드
```

---

## 라이선스

MIT
# argus-pipeline
