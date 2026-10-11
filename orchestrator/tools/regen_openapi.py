# -*- coding: utf-8 -*-
"""COS-192: байт-воспроизводимая регенерация docs/cosmo-openapi.{json,yaml}.

Источник истины — живое ``app.openapi()`` текущего рабочего дерева; формат
зафиксирован под уже принятые артефакты (COS-177/180/181/185):

  * JSON: ``json.dumps(spec, indent=2, ensure_ascii=False)`` + CRLF, без
    хвостового перевода строки (совпадает посимвольно);
  * YAML: ``yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)`` + CRLF.

Гвард соответствия — ``test_workspace_ref_readonly.py::test_docs_equal_live_app_schema``.

Usage (из любого CWD):
    python orchestrator/tools/regen_openapi.py [--check]

``--check`` — ничего не пишет, только докладывает, синхронны ли артефакты
(exit 1 при drift) — удобно для CI/предкоммитного контроля.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
JSON_PATH = DOCS / "cosmo-openapi.json"
YAML_PATH = DOCS / "cosmo-openapi.yaml"


def render_specs() -> tuple[str, str]:
    """Сгенерировать (json_text, yaml_text) из живого app.openapi()."""
    sys.path.insert(0, str(REPO_ROOT))
    # Тестовый PG по контракту COS-073 (никогда не dev-stand :5432).
    os.environ.setdefault(
        "COSMO_DATABASE_URL",
        "postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test",
    )
    from orchestrator.cosmo.api.main import app

    spec = app.openapi()
    json_text = json.dumps(spec, indent=2, ensure_ascii=False).replace("\n", "\r\n")
    yaml_text = yaml.safe_dump(spec, allow_unicode=True, sort_keys=False).replace("\n", "\r\n")
    return json_text, yaml_text


def _read_raw(path: Path) -> str:
    """Прочитать файл без newline-трансляции (иначе CRLF→LF ломает byte-сравнение)."""
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def _diff_report(path: Path, new_text: str) -> int:
    existing = _read_raw(path)
    if existing == new_text:
        print(f"{path.name}: IDENTICAL")
        return 0
    delta = list(difflib.unified_diff(
        existing.splitlines(), new_text.splitlines(), lineterm="", n=2,
        fromfile=f"docs/{path.name}", tofile=f"live/{path.name}",
    ))
    print(f"{path.name}: DRIFT ({len(delta)} diff-lines)")
    for line in delta[:80]:
        print("  " + line)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate docs/cosmo-openapi.* from live app")
    parser.add_argument("--check", action="store_true", help="only report drift, do not write")
    args = parser.parse_args()

    json_text, yaml_text = render_specs()
    if args.check:
        drift = _diff_report(JSON_PATH, json_text)
        drift |= _diff_report(YAML_PATH, yaml_text)
        return 1 if drift else 0

    for path, text in ((JSON_PATH, json_text), (YAML_PATH, yaml_text)):
        action = "unchanged" if _read_raw(path) == text else "written"
        if action == "written":
            path.write_text(text, encoding="utf-8", newline="")
        print(f"{path.name}: {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())