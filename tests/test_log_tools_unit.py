import json
from pathlib import Path
import tempfile

from mcp_stata.server import read_log, find_in_log


def _write_temp_log(content: str) -> Path:
    temp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log", encoding="utf-8")
    try:
        temp.write(content)
        temp.flush()
    finally:
        temp.close()
    return Path(temp.name)


def test_read_log_basic():
    log_path = _write_temp_log("line1\nline2\nline3\n")
    try:
        payload = json.loads(read_log(str(log_path)))
        assert payload["path"] == str(log_path)
        assert payload["offset"] == 0
        assert "line2" in payload["data"]
        assert payload["next_offset"] > 0
    finally:
        log_path.unlink(missing_ok=True)


def test_read_log_offset_and_max_bytes():
    content = "header\nalpha\nbeta\ngamma\n"
    log_path = _write_temp_log(content)
    try:
        first = json.loads(read_log(str(log_path), offset=0, max_bytes=8))
        assert first["data"]
        next_offset = first["next_offset"]
        second = json.loads(read_log(str(log_path), offset=next_offset, max_bytes=1024))
        assert second["offset"] == next_offset
        assert "gamma" in second["data"]
    finally:
        log_path.unlink(missing_ok=True)


def test_read_log_missing_file():
    payload = json.loads(read_log("/tmp/mcp_stata_missing.log"))
    assert payload["data"] == ""
    assert payload["next_offset"] == payload["offset"]


def test_find_in_log_literal_and_context():
    log_path = _write_temp_log("one\ntwo\nthree\nfour\n")
    try:
        payload = json.loads(find_in_log(str(log_path), "three", before=1, after=1))
        assert payload["matches"]
        context = payload["matches"][0]["context"]
        assert context == ["two", "three", "four"]
    finally:
        log_path.unlink(missing_ok=True)


def test_find_in_log_regex_case_sensitive():
    log_path = _write_temp_log("Alpha\nbeta\nALPHA\n")
    try:
        insensitive = json.loads(find_in_log(str(log_path), "alpha", case_sensitive=False))
        assert len(insensitive["matches"]) == 2
        sensitive = json.loads(find_in_log(str(log_path), r"^Alpha$", regex=True, case_sensitive=True))
        assert len(sensitive["matches"]) == 1
    finally:
        log_path.unlink(missing_ok=True)


def test_find_in_log_start_offset_and_max_matches():
    log_path = _write_temp_log("hit\nmiss\nhit\nmiss\nhit\n")
    try:
        first_pass = json.loads(find_in_log(str(log_path), "hit", max_matches=1, max_bytes=8))
        assert len(first_pass["matches"]) == 1
        next_offset = first_pass["next_offset"]
        second_pass = json.loads(find_in_log(str(log_path), "hit", start_offset=next_offset, max_matches=2))
        assert len(second_pass["matches"]) >= 1
    finally:
        log_path.unlink(missing_ok=True)
