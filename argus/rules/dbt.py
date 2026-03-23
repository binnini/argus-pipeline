"""
DBT_RULES — built-in classification rules for dbt pipelines.

Usage:
    from argus.rules.dbt import DBT_RULES

    argus.init(custom_rules=DBT_RULES)

    # Combine with project-specific rules:
    argus.init(custom_rules=DBT_RULES + [
        CustomRule(pattern=r"my custom pattern", error_type="my_error", ...),
    ])

Rules are checked before built-in rules, so dbt-specific patterns
take priority over generic keyword matching.
"""
from __future__ import annotations

from argus.engine.classifier import CustomRule

DBT_RULES: list[CustomRule] = [

    # ── Compilation ──────────────────────────────────────────────────────────
    # Jinja 문법 오류, undefined variable, ref() 대상 없음
    CustomRule(
        pattern=r"compilation error|jinja2?\.exceptions|undefined.*variable|"
                r"depends on a node named|ref\(.*\).*not found|model.*not found in project",
        error_type="dbt_compilation_error",
        severity="error",
        description="dbt model compilation failed — check Jinja syntax or undefined ref()",
        needs_llm=True,
    ),

    # ── Test failures (mapped to existing error types) ───────────────────────
    # not_null 테스트 실패 → null_spike (LLM이 어떤 컬럼인지 분석)
    CustomRule(
        pattern=r"not_null.*fail|fail.*not_null|"
                r"got \d+ result.*not_null|not_null.*\d+ fail",
        error_type="null_spike",
        severity="warning",
        description="dbt not_null test failed — unexpected null values in column",
        needs_llm=True,
    ),

    # relationships 테스트 실패 → schema_change (참조 대상 컬럼/테이블 변경 가능성)
    CustomRule(
        pattern=r"relationships.*fail|fail.*relationships|"
                r"referential integrity|foreign key.*violation",
        error_type="schema_change",
        severity="error",
        description="dbt relationships test failed — referential integrity violation, "
                    "possibly upstream schema change",
        needs_llm=True,
    ),

    # accepted_range 테스트 실패 → type_mismatch (범위 밖 값)
    CustomRule(
        pattern=r"accepted_range.*fail|fail.*accepted_range|"
                r"accepted_values.*fail|fail.*accepted_values",
        error_type="type_mismatch",
        severity="error",
        description="dbt accepted_range/accepted_values test failed — values outside expected range",
        needs_llm=True,
    ),

    # unique 테스트 실패 → 별도 타입 (기존 built-in에 없음)
    CustomRule(
        pattern=r"unique.*fail|fail.*unique|"
                r"got \d+ result.*unique|duplicate.*primary key",
        error_type="dbt_duplicate_key",
        severity="error",
        description="dbt unique test failed — duplicate keys detected in column",
        needs_llm=True,
    ),

    # ── Source freshness ─────────────────────────────────────────────────────
    # 소스 데이터가 기대 시간 내에 업데이트되지 않음
    CustomRule(
        pattern=r"source freshness|freshness.*error|freshness.*warn|"
                r"max_loaded_at|source.*is past|loaded \d+ hours? ago",
        error_type="dbt_source_freshness",
        severity="warning",
        description="dbt source freshness check failed — source data is stale",
        needs_llm=False,
    ),

    # ── Runtime ──────────────────────────────────────────────────────────────
    # dbt run 실패 (일반 런타임 오류 — 더 구체적인 규칙에 매칭 안 된 경우)
    CustomRule(
        pattern=r"dbt.*error|error.*running.*model|"
                r"\d+ of \d+ ERROR|finished with \d+ error",
        error_type="dbt_runtime_error",
        severity="error",
        description="dbt model run failed — check model SQL and upstream dependencies",
        needs_llm=True,
    ),
]
