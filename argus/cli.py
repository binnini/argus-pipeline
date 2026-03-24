"""
argus CLI — 프로젝트 초기화 및 유틸리티 명령어.

Usage:
    argus init          argus.toml + .env 생성 (없는 키만 추가)
    argus init --force  argus.toml 덮어쓰기 (.env는 항상 안전하게 이어쓰기)
"""
from __future__ import annotations

import sys
from pathlib import Path

TOML_TEMPLATE = """\
# Argus 파이프라인 모니터링 설정
# 비밀값(API 키, Webhook URL)은 .env 또는 환경 변수로 관리하세요.
#
# 엔트리포인트 스크립트에서 한 번만 호출하면 됩니다:
#   import argus
#   argus.init()

[llm]
# backend = "anthropic"   # ANTHROPIC_API_KEY 환경 변수 필요
backend = "ollama"
ollama_url = "http://localhost:11434"
ollama_model = "llama3.2"

[storage]
db_path = "argus.db"

# 프로젝트 공통 분류 규칙 — 필요한 만큼 [[rules]] 블록을 추가하세요.
# [[rules]]
# pattern = 'row count too low|expected ~?[\\d,]+ got [\\d,]+'
# error_type = "volume_drop"
# severity = "warning"
# description = "Source row count dropped significantly vs baseline"
# needs_llm = true
"""

# 관리할 비밀값 키 목록: (키 이름, 설명, 기본값 플레이스홀더)
ENV_KEYS: list[tuple[str, str, str]] = [
    ("ANTHROPIC_API_KEY", "Anthropic API 키 (llm.backend = anthropic 사용 시)", ""),
    ("SLACK_WEBHOOK",     "Slack Webhook URL (알림 선택)", ""),
]


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        _print_help()
        return

    command = args[0]

    if command == "init":
        force = "--force" in args
        _cmd_init(force=force)
    else:
        print(f"알 수 없는 명령어: {command!r}")
        _print_help()
        sys.exit(1)


def _cmd_init(force: bool = False) -> None:
    _init_toml(force)
    print()
    _init_env()


# ── argus.toml ────────────────────────────────────────────────────────────────

def _init_toml(force: bool) -> None:
    path = Path.cwd() / "argus.toml"

    if path.exists() and not force:
        print(f"건너뜀 (이미 존재): {path}  (덮어쓰려면 --force)")
        return

    path.write_text(TOML_TEMPLATE, encoding="utf-8")
    action = "덮어씀" if (path.exists() and force) else "생성됨"
    print(f"{action}: {path}")


# ── .env ─────────────────────────────────────────────────────────────────────

def _init_env() -> None:
    """
    .env가 없으면 새로 생성한다.
    .env가 있으면 이미 선언된 키는 건드리지 않고 누락된 키만 이어쓴다.
    """
    path = Path.cwd() / ".env"
    existing_keys = _read_env_keys(path)
    missing = [(k, desc, val) for k, desc, val in ENV_KEYS if k not in existing_keys]

    if not missing:
        print(f"건너뜀 (모든 키 이미 존재): {path}")
        return

    lines: list[str] = []

    if not path.exists():
        lines.append("# Argus 비밀값 — 이 파일은 버전 관리에서 제외하세요 (.gitignore)\n")
    else:
        # 기존 파일에 이어쓸 때 빈 줄로 구분
        lines.append("\n# Argus (argus init으로 추가됨)\n")

    for key, desc, default in missing:
        lines.append(f"# {desc}\n")
        lines.append(f"{key}={default}\n")

    with open(path, "a", encoding="utf-8") as f:
        f.writelines(lines)

    action = "생성됨" if not existing_keys else "이어씀"
    added = ", ".join(k for k, _, _ in missing)
    print(f"{action}: {path}  ({added})")


def _read_env_keys(path: Path) -> set[str]:
    """기존 .env에서 이미 선언된 키 이름을 추출한다."""
    if not path.exists():
        return set()
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


# ── help ─────────────────────────────────────────────────────────────────────

def _print_help() -> None:
    print("Usage:")
    print("  argus init           argus.toml + .env 생성 (없는 키만 추가)")
    print("  argus init --force   argus.toml 덮어쓰기 (.env는 항상 안전하게 이어쓰기)")
