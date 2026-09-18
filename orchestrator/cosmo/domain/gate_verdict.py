# -*- coding: utf-8 -*-
"""COS-123: Pre-flight Quality Gate Verdict Engine.

Сканирование содержимого файлов перед коммитом на секреты и запрещённые
паттерны. Никакого форжа не вызываем — чистая статика по содержимому, которое
FE уже прочитал (draft/head/blob).

Правила возвращают список GateViolation; вердикт вычисляется как:
  - BLOCK: хотя бы одно BLOCK-нарушение
  - WARN:  хотя бы одно WARN-нарушение (и ноль BLOCK)
  - PASS:  нарушений нет
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Literal

Severity = Literal["BLOCK", "WARN"]


# ── Dataclass (plain, not Pydantic — Pydantic DTO в domain/workspace.py) ──


@dataclass
class Violation:
    """Сырое нарушение из движка."""
    path: str = ""
    rule_id: str = ""
    severity: Severity = "BLOCK"
    message: str = ""
    line_number: int = 0
    snippet: str = ""


# ── BLOCK rules (private keys, live tokens) ──────────────────────────────────


# RSA / OPENSSH / EC private key headers
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
    re.MULTILINE,
)

# AWS access key ID: AKIA + 16 uppercase alphanum
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

# GitHub personal access token: ghp_ / gho_ / ghu_ / ghs_ / ghr_ + 36+ chars
_GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")

# GitLab personal access token: glpat- + chars
_GITLAB_TOKEN_RE = re.compile(r"\bglpat-[A-Za-z0-9\-_]{20,}\b")

# Generic secret assignment in config-like files (password/token/secret with value)
# Matches: password = "abc123" or token: hardcoded123
# But NOT: password = $ENV_VAR or token: ${VAR}
# Note: (?!\s*[\$\{]) must include \s* to prevent backtracking past it.
_CONFIG_SECRET_RE = re.compile(
    r'^\s*(?:password|passwd|secret|token|api_key|apikey)\s*[=:](?!\s*[\$\{])'
    r'[\s\"\']*([^\"\'#\n\r]{4,})',
    re.MULTILINE | re.IGNORECASE,
)

# OpenBao / Vault token: hvs.xxx or s.xxx
_VAULT_TOKEN_RE = re.compile(r"\bhvs\.[A-Za-z0-9_\-]{20,}\b")


# ── WARN rules (suspicious patterns, forbidden file types) ───────────────────


# JWT-style token: eyJxxx.yyy.zzz
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{10,}\b")

# Generic "token = xxxx" in any file (less strict match)
# Matches: token: "abc123", "api_key": "sk-123", api_key = "secret"
_GENERIC_TOKEN_RE = re.compile(
    r'[\"\']?(?:token|api[_-]?key|api[_-]?secret)[\"\']?\s*[=:]\s*[\"\'][^\"\'$]{6,}[\"\']',
    re.IGNORECASE,
)

# Forbidden file paths (regex match against file name)
_FORBIDDEN_FILE_RE = re.compile(
    r"(?:^|[/\\])(\.env|.*\.pem|.*\.key|credentials\.json|"
    r"service-account.*\.json|id_rsa|id_ed25519|.*_rsa)$",
    re.IGNORECASE,
)

# .env content: KEY=VALUE (catching potential exposure in non-.env files)
_ENV_CONTENT_RE = re.compile(r"^(?:[A-Z][A-Z0-9_]{2,})\s*=\s*.+", re.MULTILINE)


# ── Rule registry ────────────────────────────────────────────────────────────

_Rule = tuple[str, re.Pattern, Severity, str]
_RULES: list[_Rule] = [
    # ── BLOCK ──
    ("private-key", _PRIVATE_KEY_RE, "BLOCK", "Private key found in file"),
    ("aws-key", _AWS_KEY_RE, "BLOCK", "AWS access key exposed"),
    ("github-token", _GITHUB_TOKEN_RE, "BLOCK", "GitHub personal access token exposed"),
    ("gitlab-token", _GITLAB_TOKEN_RE, "BLOCK", "GitLab personal access token exposed"),
    ("vault-token", _VAULT_TOKEN_RE, "BLOCK", "Vault/OpenBao token exposed"),
    (
        "config-secret",
        _CONFIG_SECRET_RE,
        "BLOCK",
        "Hardcoded password/secret in configuration",
    ),
    # ── WARN ──
    ("jwt-exposed", _JWT_RE, "WARN", "JWT token found (may be stale)"),
    ("generic-token", _GENERIC_TOKEN_RE, "WARN", "Generic token/key assignment detected"),
    ("env-content", _ENV_CONTENT_RE, "WARN", "Environment variable assignment detected (possible .env exposure)"),
]


# ── Worker function ──────────────────────────────────────────────────────────


def _find_line(content: str, pos: int) -> int:
    """Номер строки (1-based) по позиции в тексте."""
    return content[:pos].count("\n") + 1


def _snippet(content: str, pos: int, before: int = 3, after: int = 40) -> str:
    """Обрезок строки вокруг позиции."""
    start = max(pos - before, 0)
    end = min(pos + after, len(content))
    snip = content[start:end].replace("\n", " ").replace("\r", "")
    return snip[:80]


def scan_file(path: str, content: str) -> list[Violation]:
    """Сканирует содержимое одного файла. Возвращает список нарушений."""
    violations: list[Violation] = []

    if not content:
        return violations

    # ── Step 1: Regex rules ──
    for rule_id, pattern, severity, message in _RULES:
        for m in pattern.finditer(content):
            line_no = _find_line(content, m.start())
            snip = _snippet(content, m.start())
            violations.append(
                Violation(
                    path=path,
                    rule_id=rule_id,
                    severity=severity,
                    message=message,
                    line_number=line_no,
                    snippet=snip,
                )
            )

    # ── Step 2: Forbidden file path ──
    if _FORBIDDEN_FILE_RE.search(path):
        violations.append(
            Violation(
                path=path,
                rule_id="forbidden-file",
                severity="BLOCK",
                message=f"Forbidden file type detected: {path}",
                line_number=0,
                snippet=path.rsplit("/", 1)[-1] if "/" in path else path,
            )
        )

    return violations


def compute_verdict(violations: list[Violation]) -> Literal["PASS", "WARN", "BLOCK"]:
    """Вычисляет итоговый вердикт по набору нарушений."""
    if not violations:
        return "PASS"
    if any(v.severity == "BLOCK" for v in violations):
        return "BLOCK"
    return "WARN"


# ── COS-132: потоковое сканирование дерева репозитория ───────────────────────

# Потолок на один blob: больше — не читаем и не сканируем.
MAX_SCAN_BLOB_BYTES = 2 * 1024 * 1024


def _is_binary_bytes(data: bytes) -> bool:
    """Бинарность по NUL-байту в начале содержимого."""
    return b"\x00" in data[:8192]


def _decode_text(data: bytes) -> str | None:
    """bytes → utf-8 str либо None (бинарный/не декодируется)."""
    if _is_binary_bytes(data):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


@dataclass
class ScanTreeResult:
    """Агрегат скана дерева: сколько отсканировано/чисто/пропущено."""
    scanned_files: int = 0
    clean_files: int = 0
    skipped_files: int = 0
    violations: list[Violation] = field(default_factory=list)


def scan_tree(
    tree_entries: Any,
    blob_loader: Callable[[Any], bytes | str | None],
    max_bytes: int = MAX_SCAN_BLOB_BYTES,
) -> ScanTreeResult:
    """Потоково сканирует blob-записи дерева Gitea.

    `tree_entries` — итерируемое GiteaTreeEntry (не-blob пропускаются).
    `blob_loader(entry)` → bytes | str | None; None/исключение = пропуск.
    Пропускаются: бинарные, больше `max_bytes` (по tree size или факту),
    не декодируемые в utf-8. `clean_files` — отсканированные без нарушений.
    """
    result = ScanTreeResult()

    for entry in tree_entries:
        if getattr(entry, "type", "blob") != "blob":
            continue
        size = getattr(entry, "size", None)
        if size is not None and size > max_bytes:
            result.skipped_files += 1
            continue

        try:
            data = blob_loader(entry)
        except Exception:  # noqa: BLE001 — битый blob не роняет скан
            result.skipped_files += 1
            continue
        if data is None:
            result.skipped_files += 1
            continue
        if isinstance(data, str):
            data = data.encode("utf-8")
        if len(data) > max_bytes:
            result.skipped_files += 1
            continue

        text = _decode_text(data)
        if text is None:
            result.skipped_files += 1
            continue

        result.scanned_files += 1
        path = getattr(entry, "path", "")
        found = scan_file(path, text)
        if found:
            result.violations.extend(found)
        else:
            result.clean_files += 1

    return result


# ── COS-132: SARIF 2.1.0 serializer ──────────────────────────────────────────

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
SARIF_TOOL_NAME = "Cosmoport Security Gate"
SARIF_TOOL_VERSION = "0.2.0"

# rule_id → (severity, human message); forbidden-file добавляется вручную.
_RULE_META: dict[str, tuple[Severity, str]] = {
    rule_id: (severity, message)
    for rule_id, _pattern, severity, message in _RULES
}
_RULE_META["forbidden-file"] = ("BLOCK", "Forbidden file type detected")


def _sarif_level(severity: Severity) -> str:
    """SARIF level: BLOCK → error, WARN → warning."""
    return "error" if severity == "BLOCK" else "warning"


def to_sarif(
    violations: list[Violation],
    *,
    tool_version: str = SARIF_TOOL_VERSION,
    information_uri: str = "",
) -> dict:
    """Сериализует нарушения в SARIF 2.1.0 (runs/tool.driver/rules/results).

    rules — уникальные rule_id из результатов; каждый result несёт
    locations[0].physicalLocation с artifactLocation.uri и region.startLine.
    """
    rule_ids: list[str] = []
    seen: set[str] = set()
    for v in violations:
        if v.rule_id not in seen:
            seen.add(v.rule_id)
            rule_ids.append(v.rule_id)

    rules = []
    for rule_id in rule_ids:
        severity, message = _RULE_META.get(rule_id, ("BLOCK", rule_id))
        rules.append({
            "id": rule_id,
            "name": rule_id,
            "shortDescription": {"text": message},
            "defaultConfiguration": {"level": _sarif_level(severity)},
        })

    results = []
    for v in violations:
        region: dict[str, Any] = {
            "startLine": v.line_number if v.line_number > 0 else 1,
        }
        if v.snippet:
            region["snippet"] = {"text": v.snippet}
        results.append({
            "ruleId": v.rule_id,
            "level": _sarif_level(v.severity),
            "message": {"text": v.message},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": v.path},
                    "region": region,
                },
            }],
        })

    driver: dict[str, Any] = {
        "name": SARIF_TOOL_NAME,
        "version": tool_version,
        "rules": rules,
    }
    if information_uri:
        driver["informationUri"] = information_uri

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [{"tool": {"driver": driver}, "results": results}],
    }