# -*- coding: utf-8 -*-
"""COS-087: внешний append-only якорь головы evidence-цепочки.

Threat model честной границы (COS-082): атакующий с полным доступом на
запись может пере-подписать весь суффикс цепочки — internal verify от
СОХРАНЁННЫХ якорей пройдёт, потому что якоря тоже переподписаны. Замыкание
головы вовне (append-only sink) делает переподпись детектируемой: у attack
нет права записи в sink.

COS-093: два sink-бэкенда за ОДНИМ контрактом (publish/read/is_enabled):

  - ``file`` (default) — audit-file JSONL, append-only,
    ``COSMO_EVIDENCE_ANCHOR_FILE``. Файл только дополняется (никогда
    не rewrite), одна строка на публикацию головы. Pure Box / airgap.
  - ``s3`` — object-store (S3/MinIO): ключ ``{prefix}{run_id}.jsonl``,
    публикация = GET-текущего тела + append строки + PUT новой версии.
    Append-only гарантируется ВЕРСИОНИРОВАНИЕМ бакета (PUT создаёт новую
    immutable-версию; старые головы остаются в истории версий) —
    приложение включает versioning best-effort при первой публикации,
    жёсткая гарантия лежит на bucket policy. Single-writer: запись ведёт
    один процесс (GET-modify-PUT без CAS, гонки двух райтеров не
    покрываются контрактом). Конфиг — ``PK_MINIO_URL`` /
    ``PK_MINIO_ACCESS_KEY`` / ``PK_MINIO_SECRET_KEY`` (канон startup.py),
    бакет ``COSMO_EVIDENCE_ANCHOR_S3_BUCKET`` (default ``cosmo-evidence``).

Выбор бэкенда — конфиг, не код: ``COSMO_EVIDENCE_ANCHOR_BACKEND``
= ``file`` (default) | ``s3``. Контракт publish/verify НЕ меняется
(COS-087): фейл записи → исключение (fail visible), недоступность на
чтении → честный ``unknown_anchor``.

Статусы (read-side, честно, одинаковы для обоих бэкендов):
  - "ok"             — якорь прочитан, сверка выполнена (match/mismatch в integrity)
  - "unknown_anchor" — sink недоступен/нет записи для run: внешнего
                       доказательства нет, и мы НЕ изображаем, что оно есть
  - "disabled"       — якорь не сконфигурирован (env не задан)

Хеш головы = СОХРАНЁННЫЙ ``_chain_hash`` последней запечатанной строки
(тот же, что пишет write-path) — НЕ hash rebuild-вида chain API.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import urllib.parse
from typing import Any

logger = logging.getLogger("cosmoport.evidence_anchor")


def datetime_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

ANCHOR_FILE_ENV = "COSMO_EVIDENCE_ANCHOR_FILE"
BACKEND_ENV = "COSMO_EVIDENCE_ANCHOR_BACKEND"  # "file" (default) | "s3"
S3_BUCKET_ENV = "COSMO_EVIDENCE_ANCHOR_S3_BUCKET"
S3_PREFIX_ENV = "COSMO_EVIDENCE_ANCHOR_S3_PREFIX"

_S3_KEY_PREFIX_DEFAULT = "evidence-anchor/"
_S3_TIMEOUT = 10.0


# ══════════════════════════════════════════════════════════════════
# Backend dispatch (COS-093): выбор sink'а — конфиг, не код
# ══════════════════════════════════════════════════════════════════

def backend() -> str:
    """Активный sink-бэкенд: "file" (default) | "s3" | неизвестное значение."""
    raw = os.getenv(BACKEND_ENV, "").strip().lower()
    if not raw:
        return "file"
    return raw


def sink_path() -> str | None:
    """Путь к append-only якорному файлу (env читается на каждый вызов).

    Только для file-бэкенда (default); в s3-режиме вернёт None —
    путь не применим, health-проба читает s3-ветку.
    """
    if backend() != "file":
        return None
    raw = os.getenv(ANCHOR_FILE_ENV, "").strip()
    if not raw:
        return None
    return os.path.expandvars(raw)


def is_enabled() -> bool:
    """Якорение активно: backend=file и файл задан, либо backend=s3
    и S3-конфигурация задана (endpoint+bucket)."""
    if backend() == "s3":
        return s3_config() is not None
    return sink_path() is not None


def publish_head(run_id: str, chain_hash: str, entry_id: str | None = None) -> None:
    """Опубликовать голову run'а в sink (append-only, только после commit).

    Фейл записи → исключение: якорь — часть контракта записи, тихо
    потерять доказательство нельзя (fail visible). Если якорение не
    сконфигурировано — no-op (честный disabled на read-стороне).
    """
    if backend() == "s3":
        sink = _s3_sink_for_publish()
        if sink is None:
            return
        sink.publish(run_id, chain_hash, entry_id)
        return
    _publish_to_file(run_id, chain_hash, entry_id)


def read_head(run_id: str) -> dict[str, Any]:
    """Прочитать внешний якорь головы run'а (активный backend).

    Returns: {"status": "ok", "anchored_head": ..., "anchored_at": ...}
           | {"status": "unknown_anchor", "detail": ...}
    """
    if backend() == "s3":
        sink = _s3_sink_for_read()
        if sink is None:
            return {"status": "unknown_anchor", "detail": "anchor sink not configured"}
        return sink.read(run_id)
    return _read_file(run_id)


# ── file backend (COS-087, default) ────────────────────────────────

def _publish_to_file(run_id: str, chain_hash: str, entry_id: str | None) -> None:
    path = sink_path()
    if not path:
        return
    record = {
        "ts": datetime_iso(),
        "run_id": run_id,
        "chain_hash": chain_hash,
        "entry_id": entry_id,
    }
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    # append-only: только дозапись, никаких rewrite/усечений
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _read_file(run_id: str) -> dict[str, Any]:
    path = sink_path()
    if path is None:
        return {"status": "unknown_anchor", "detail": "anchor sink not configured"}
    if not os.path.exists(path):
        return {
            "status": "unknown_anchor",
            "detail": f"anchor sink file does not exist: {path}",
        }
    try:
        last: dict[str, Any] | None = None
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("run_id") == run_id:
                    last = rec
    except OSError as exc:
        return {"status": "unknown_anchor", "detail": f"sink unreadable: {exc}"}
    if last is None:
        return {
            "status": "unknown_anchor",
            "detail": "no anchor published for run",
        }
    return {
        "status": "ok",
        "anchored_head": last.get("chain_hash"),
        "anchored_at": last.get("ts"),
    }


# ── S3/MinIO backend (COS-093) ─────────────────────────────────────

def s3_config() -> dict[str, str] | None:
    """Конфиг S3 sink из env. Endpoint — конвенция startup.py (PK_MINIO_*).

    Returns None, если endpoint не задан (s3-якорь не сконфигурирован).
    """
    endpoint = os.getenv("PK_MINIO_URL", "").strip().rstrip("/")
    if not endpoint:
        return None
    return {
        "endpoint": endpoint,
        "access_key": os.getenv("PK_MINIO_ACCESS_KEY", "cosmo"),
        "secret_key": os.getenv("PK_MINIO_SECRET_KEY", "cosmo-minio-dev"),
        "bucket": os.getenv(S3_BUCKET_ENV, "cosmo-evidence").strip() or "cosmo-evidence",
        "prefix": os.getenv(S3_PREFIX_ENV, "evidence-anchor/"),
        "region": os.getenv(S3_REGION_ENV, "us-east-1"),
    }


S3_REGION_ENV = "COSMO_EVIDENCE_ANCHOR_S3_REGION"


class S3AnchorSink:
    """Object-store sink якоря (S3/MinIO): тот же контракт publish/read.

    Append-only замена: объект ``{prefix}{run_id}.jsonl`` хранит
    накопленный JSONL якорей; каждая публикация = GET + append + PUT.
    Включённое S3-версионирование делает каждую версию объекта
    immutable-записью (серверная история = append-only журнал); попытка
    включить versioning — best-effort один раз на sink (жёсткая гарантия
    остаётся на bucket policy). Читаем последнюю версию объекта: GET
    без versionId отдаёт её по S3-семантике.

    Publish фейл → исключение (fail visible). Read фейлы → честный
    unknown_anchor: недоступный объект-store НЕ притворяется
    подтверждённым якорем.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        prefix: str = "evidence-anchor/",
        region: str = "us-east-1",
        client: Any = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._bucket = bucket
        self._prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._host = urllib.parse.urlsplit(self._endpoint).netloc
        if client is not None:
            self._client = client
        else:
            import httpx
            self._client = httpx.Client(
                base_url=self._endpoint,
                timeout=httpx.Timeout(10.0),
            )
        self._versioning_checked = False

    # ── S3 helpers ──

    def _object_key(self, run_id: str) -> str:
        return f"{self._prefix}{run_id}.jsonl"

    def _request(self, method: str, path: str, params: dict[str, str] | None = None,
                 content: bytes | None = None, headers: dict[str, str] | None = None):
        """Подписанный (SigV4) S3-запрос: MinIO Basic auth не принимает."""
        sig = s3_sigv4_headers(
            method, self._host, path, params,
            self._access_key, self._secret_key, self._region, content,
        )
        all_headers = {**(headers or {}), **sig}
        return self._client.request(
            method, path, params=params or None, content=content,
            headers=all_headers,
        )

    def _ensure_versioning(self) -> None:
        """Best-effort включить versioning бакета (один раз на sink).

        Versioning — append-only замена: каждый PUT создаёт новую
        immutable-версию, серверная история хранит все головы. Фейл
        настройки — warning (bucket может быть уже настроен политикой;
        у ограниченных кред может не быть права на versioning config) —
        publish при этом не блокируется.
        """
        if self._versioning_checked:
            return
        self._versioning_checked = True
        url = f"/{self._bucket}"
        params = {"versioning": ""}
        body = (
            '<VersioningConfiguration '
            'xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            "<Status>Enabled</Status></VersioningConfiguration>"
        )
        try:
            r = self._request("PUT", url, params=params, content=body.encode("utf-8"))
            if r.status_code not in (200, 201):
                logger.warning(
                    "evidence anchor: bucket '%s' versioning not enabled "
                    "(HTTP %d) — append-only гарантия лежит на bucket policy",
                    self._bucket, r.status_code,
                )
        except Exception as exc:  # noqa: BLE001 — best-effort по дизайну
            logger.warning(
                "evidence anchor: versioning enable failed (best-effort): %s", exc,
            )

    # ── publish / read ──

    def publish(self, run_id: str, chain_hash: str, entry_id: str | None = None) -> None:
        record = {
            "ts": datetime_iso(),
            "run_id": run_id,
            "chain_hash": chain_hash,
            "entry_id": entry_id,
        }
        existing = self._get_body(run_id)
        if existing and not existing.endswith("\n"):
            existing += "\n"
        body = existing + json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
        self._ensure_versioning()
        try:
            resp = self._request(
                "PUT", f"/{self._bucket}/{self._object_key(run_id)}",
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
            )
        except Exception as exc:
            raise RuntimeError(f"anchor S3 publish failed: {exc}") from exc
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"anchor S3 publish failed: HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )

    def read(self, run_id: str) -> dict[str, Any]:
        try:
            resp = self._request("GET", f"/{self._bucket}/{self._object_key(run_id)}")
        except Exception as exc:
            return {
                "status": "unknown_anchor",
                "detail": f"anchor sink unreadable: {exc}",
            }
        if resp.status_code == 404:
            return {
                "status": "unknown_anchor",
                "detail": "no anchor object in bucket for run",
            }
        if resp.status_code != 200:
            return {
                "status": "unknown_anchor",
                "detail": f"anchor sink HTTP {resp.status_code}",
            }
        try:
            last: dict[str, Any] | None = None
            for line in resp.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("run_id") == run_id:
                    last = rec
        except (ValueError, AttributeError) as exc:
            return {
                "status": "unknown_anchor",
                "detail": f"anchor object corrupt: {exc}",
            }
        if last is None:
            return {
                "status": "unknown_anchor",
                "detail": "no anchor published for run",
            }
        return {
            "status": "ok",
            "anchored_head": last.get("chain_hash"),
            "anchored_at": last.get("ts"),
        }

    # ── internal: read-before-append ──

    def _get_body(self, run_id: str) -> str:
        """Тело текущей версии объекта: 404 → "" (первая публикация),
        прочий фейл → исключение (fail visible на записи)."""
        try:
            resp = self._request("GET", f"/{self._bucket}/{self._object_key(run_id)}")
        except Exception as exc:
            raise RuntimeError(f"anchor S3 read-before-append failed: {exc}") from exc
        if resp.status_code == 404:
            return ""
        if resp.status_code != 200:
            raise RuntimeError(
                f"anchor S3 read-before-append failed: HTTP {resp.status_code}"
            )
        return resp.text


_S3_SINK_CACHE: tuple[tuple, Any] | None = None


def s3_sigv4_headers(
    method: str,
    host: str,
    path: str,
    params: dict[str, str] | None,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
    content: bytes | None = None,
) -> dict[str, str]:
    """Минимальный AWS Signature V4 (stdlib) для S3 API MinIO/Ceph.

    MinIO отклоняет HTTP Basic auth для S3 API ("Please use
    AWS4-HMAC-SHA256"), поэтому подписываем каждый запрос: path-style,
    payload hash реального тела (UNSIGNED-PAYLOAD для пустых GET).
    Возвращает заголовки x-amz-date / x-amz-content-sha256 / Authorization.
    """
    import hashlib
    import hmac
    import urllib.parse

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = (
        hashlib.sha256(content).hexdigest() if content else "UNSIGNED-PAYLOAD"
    )

    # canonical URI: посегментный percent-encode, '/' сохраняем
    canonical_uri = urllib.parse.quote(path, safe="/-._~")
    # canonical query: отсортированные k=v с RFC3986-кодированием
    enc = lambda s: urllib.parse.quote(str(s), safe="-._~")  # noqa: E731
    cq = "&".join(
        f"{enc(k)}={enc(v)}"
        for k, v in sorted((params or {}).items())
    )

    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"

    canonical_request = "\n".join([
        method.upper(), canonical_uri, cq, canonical_headers, signed_headers,
        payload_hash,
    ])
    scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k_date = _hmac(("AWS4" + secret_key).encode(), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, "s3")
    k_signing = _hmac(k_service, "aws4_request")
    signature = hmac.new(
        k_signing, string_to_sign.encode(), hashlib.sha256,
    ).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": authorization,
    }


def _build_s3_sink(cfg: dict[str, str]) -> "S3AnchorSink":
    return S3AnchorSink(
        cfg["endpoint"], cfg["access_key"], cfg["secret_key"],
        bucket=cfg["bucket"], prefix=cfg["prefix"], region=cfg["region"],
    )


def _s3_sink_for_publish() -> "S3AnchorSink":
    """Sink для publish-стороны: misconfig → fail visible (raise)."""
    global _S3_SINK_CACHE
    cfg = s3_config()
    if cfg is None:
        raise RuntimeError(
            "COSMO_EVIDENCE_ANCHOR_BACKEND=s3, but PK_MINIO_URL is not set — "
            "якорь обязан писаться, тихо потерять доказательство нельзя"
        )
    key = tuple(sorted(cfg.items()))
    if _S3_SINK_CACHE is not None and _S3_SINK_CACHE[0] == key:
        return _S3_SINK_CACHE[1]
    sink = _build_s3_sink(cfg)
    _S3_SINK_CACHE = (key, sink)
    return sink


def _s3_sink_for_read():
    """Sink для read-стороны: конфиг не задан → честный unknown_anchor."""
    global _S3_SINK_CACHE
    cfg = s3_config()
    if cfg is None:
        return None
    key = tuple(sorted(cfg.items()))
    if _S3_SINK_CACHE is not None and _S3_SINK_CACHE[0] == key:
        return _S3_SINK_CACHE[1]
    sink = _build_s3_sink(cfg)
    _S3_SINK_CACHE = (key, sink)
    return sink
