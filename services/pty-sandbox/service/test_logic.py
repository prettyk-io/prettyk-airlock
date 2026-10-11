# -*- coding: utf-8 -*-
"""PTY-SANDBOX-1: unit-тесты чистой логики (без docker/fastapi).

Запуск: pytest services/pty-sandbox/service/test_logic.py -q
"""
import io
import os
import sys
import tarfile

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from logic import (  # noqa: E402
    MAX_ARGS,
    MIN_TTL_S,
    RESIZE_COLS_MAX,
    RESIZE_ROWS_MAX,
    clamp_resize,
    clamp_ttl,
    normalize_relpath,
    parse_allowlist,
    sanitize_delivery_tar,
    session_labels,
    validate_args,
    validate_id_field,
    validate_tool,
)


class TestAllowlist:
    def test_parse_normalizes(self):
        assert parse_allowlist("git, ls ,cat,,git") == ("git", "ls", "cat")

    def test_parse_empty(self):
        assert parse_allowlist("") == ()
        assert parse_allowlist("  ,  ") == ()

    def test_tool_validation(self):
        allowlist = parse_allowlist("git,ls")
        assert validate_tool("git", allowlist)
        assert not validate_tool("sh", allowlist)
        assert not validate_tool("", allowlist)
        assert not validate_tool("GIT", allowlist)  # точное совпадение


class TestTtl:
    def test_default(self):
        assert clamp_ttl(None, 900, 3600) == 900

    def test_clamp_low(self):
        assert clamp_ttl(1, 900, 3600) == MIN_TTL_S

    def test_clamp_high(self):
        assert clamp_ttl(99999, 900, 3600) == 3600

    def test_empty_string_is_default(self):
        assert clamp_ttl("", 900, 3600) == 900

    def test_invalid(self):
        with pytest.raises(ValueError):
            clamp_ttl("abc", 900, 3600)


class TestArgs:
    def test_ok(self):
        assert validate_args(["a", "b"]) == ["a", "b"]
        assert validate_args(None) == []

    def test_too_many(self):
        with pytest.raises(ValueError):
            validate_args(["x"] * (MAX_ARGS + 1))

    def test_too_long(self):
        with pytest.raises(ValueError):
            validate_args(["y" * 300])

    def test_nul_rejected(self):
        with pytest.raises(ValueError):
            validate_args(["a\x00b"])

    def test_not_list(self):
        with pytest.raises(ValueError):
            validate_args("rm -rf /")


class TestIdField:
    def test_ok(self):
        assert validate_id_field("run-1", "run_id") == "run-1"
        assert validate_id_field("cosmo/pipeline-fixture", "repo") == "cosmo/pipeline-fixture"
        assert validate_id_field("deadbeef", "commit_sha") == "deadbeef"

    def test_unsafe_rejected(self):
        for bad in ("", " ", "a b", "a;b", "a$(b)", "a`b`", "a|b", "a&b"):
            with pytest.raises(ValueError):
                validate_id_field(bad, "run_id")

    def test_labels(self):
        labels = session_labels("sid1", "run1")
        assert labels["cosmo.pty.session"] == "sid1"
        assert labels["cosmo.pty.run_id"] == "run1"
        assert labels["managed-by"] == "pty-sandbox"


def _make_tar(members) -> bytes:
    """Собрать tar: (name, data|None) — None это DIRTYPE-запись."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tf:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            if data is None:
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o777
                tf.addfile(ti)
            else:
                ti.size = len(data)
                ti.mode = 0o777
                tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


class TestResize:
    def test_ok(self):
        assert clamp_resize(40, 120) == (40, 120)
        assert clamp_resize("80", "24") == (80, 24)

    def test_clamp_high(self):
        assert clamp_resize(10**6, 10**6) == (RESIZE_ROWS_MAX, RESIZE_COLS_MAX)

    def test_invalid(self):
        for bad in (0, -1, None, "abc", True):
            with pytest.raises(ValueError):
                clamp_resize(bad, 80)
        with pytest.raises(ValueError):
            clamp_resize(40, True)


class TestRelpath:
    def test_ok(self):
        assert normalize_relpath("src/main.py") == "src/main.py"
        assert normalize_relpath("./a/b") == "a/b"
        assert normalize_relpath("dir/") == "dir"
        assert normalize_relpath("a/b/") == "a/b"
        assert normalize_relpath("././x") == "x"

    def test_unsafe(self):
        for bad in ("", "/etc/passwd", "../x", "a/../b", "a/./b", "a\\b",
                    "C:/x", "a//b", ".", "..", "a\x00b", "./"):
            assert normalize_relpath(bad) is None, bad


class TestDeliveryTar:
    def test_happy(self):
        raw = _make_tar([
            ("README.md", b"hello"),
            ("src/", None),
            ("src/main.py", b"print('x')"),
        ])
        clean, reason, stats = sanitize_delivery_tar(
            raw, max_entries=100, max_unpacked_bytes=10**6)
        assert reason == "" and clean is not None
        assert stats["files"] == 2 and stats["dirs"] == 1 and stats["bytes"] == 15
        with tarfile.open(fileobj=io.BytesIO(clean), mode="r:") as tf:
            members = {m.name: m for m in tf.getmembers()}
            assert tf.extractfile("README.md").read() == b"hello"
        assert set(members) == {"README.md", "src", "src/main.py"}
        for m in members.values():
            assert m.uid == 0 and m.gid == 0
        assert members["README.md"].mode == 0o644
        assert members["src/main.py"].mode == 0o644
        assert members["src"].mode == 0o755 and members["src"].isdir()

    def test_parents_synthesized(self):
        raw = _make_tar([("a/b/c.txt", b"x")])
        clean, reason, _ = sanitize_delivery_tar(
            raw, max_entries=100, max_unpacked_bytes=10**6)
        assert reason == "" and clean is not None
        with tarfile.open(fileobj=io.BytesIO(clean), mode="r:") as tf:
            names = {m.name for m in tf.getmembers()}
        assert names == {"a", "a/b", "a/b/c.txt"}

    def test_duplicates_collapse(self):
        raw = _make_tar([("f.txt", b"one"), ("f.txt", b"two")])
        clean, reason, stats = sanitize_delivery_tar(
            raw, max_entries=100, max_unpacked_bytes=10**6)
        assert reason == "" and clean is not None
        assert stats["files"] == 1

    def test_bad_archive(self):
        clean, reason, _ = sanitize_delivery_tar(
            b"not a tar at all", max_entries=100, max_unpacked_bytes=10**6)
        assert clean is None and reason == "bad_archive"

    def test_unsafe_path(self):
        raw = _make_tar([("../evil.txt", b"x")])
        clean, reason, _ = sanitize_delivery_tar(
            raw, max_entries=100, max_unpacked_bytes=10**6)
        assert clean is None and reason == "unsafe_path"

    def test_unsupported_entry(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:") as tf:
            ti = tarfile.TarInfo("link")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc/passwd"
            tf.addfile(ti)
        clean, reason, _ = sanitize_delivery_tar(
            buf.getvalue(), max_entries=100, max_unpacked_bytes=10**6)
        assert clean is None and reason == "unsupported_entry"

    def test_too_many_entries(self):
        raw = _make_tar([(f"f{i}.txt", b"x") for i in range(5)])
        clean, reason, _ = sanitize_delivery_tar(
            raw, max_entries=3, max_unpacked_bytes=10**6)
        assert clean is None and reason == "too_many_entries"

    def test_too_large_unpacked(self):
        raw = _make_tar([("big.bin", b"x" * 100)])
        clean, reason, _ = sanitize_delivery_tar(
            raw, max_entries=100, max_unpacked_bytes=10)
        assert clean is None and reason == "too_large_unpacked"

