import hashlib
import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

from .stata_client import StataClient
from .config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_ARROW_LIMIT,
    MAX_CHARS,
    MAX_LIMIT,
    MAX_REQUEST_BYTES,
    MAX_VARS,
    TOKEN_TTL_S,
    VIEW_TTL_S,
)


def _stable_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass
class UIChannelInfo:
    base_url: str
    token: str
    expires_at: int


@dataclass
class ViewHandle:
    view_id: str
    dataset_id: str
    frame: str
    filter_expr: str
    obs_indices: list[int]
    filtered_n: int
    created_at: float
    last_access: float


class UIChannelManager:
    def __init__(
        self,
        client: StataClient,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        token_ttl_s: int = TOKEN_TTL_S,
        view_ttl_s: int = VIEW_TTL_S,
        max_limit: int = MAX_LIMIT,
        max_vars: int = MAX_VARS,
        max_chars: int = MAX_CHARS,
        max_request_bytes: int = MAX_REQUEST_BYTES,
        max_arrow_limit: int = MAX_ARROW_LIMIT,
    ):
        self._client = client
        self._host = host
        self._port = port
        self._token_ttl_s = token_ttl_s
        self._view_ttl_s = view_ttl_s
        self._max_limit = max_limit
        self._max_vars = max_vars
        self._max_chars = max_chars
        self._max_request_bytes = max_request_bytes
        self._max_arrow_limit = max_arrow_limit

        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

        self._token: str | None = None
        self._expires_at: int = 0

        self._dataset_version: int = 0
        self._dataset_id_cache: str | None = None
        self._dataset_id_cache_at_version: int = -1

        self._views: dict[str, ViewHandle] = {}

    def notify_potential_dataset_change(self) -> None:
        with self._lock:
            self._dataset_version += 1
            self._dataset_id_cache = None
            self._views.clear()

    def get_channel(self) -> UIChannelInfo:
        self._ensure_http_server()
        with self._lock:
            self._ensure_token()
            assert self._httpd is not None
            port = self._httpd.server_address[1]
            base_url = f"http://{self._host}:{port}"
            return UIChannelInfo(base_url=base_url, token=self._token or "", expires_at=self._expires_at)

    def capabilities(self) -> dict[str, bool]:
        return {"dataBrowser": True, "filtering": True, "sorting": True, "arrowStream": True}

    def current_dataset_id(self) -> str:
        with self._lock:
            if self._dataset_id_cache is not None and self._dataset_id_cache_at_version == self._dataset_version:
                return self._dataset_id_cache

        state = self._client.get_dataset_state()
        payload = {
            "version": self._dataset_version,
            "frame": state.get("frame"),
            "n": state.get("n"),
            "k": state.get("k"),
            "sortlist": state.get("sortlist"),
        }
        digest = _stable_hash(payload)

        with self._lock:
            self._dataset_id_cache = digest
            self._dataset_id_cache_at_version = self._dataset_version
            return digest

    def get_view(self, view_id: str) -> Optional[ViewHandle]:
        now = time.time()
        with self._lock:
            self._evict_expired_locked(now)
            view = self._views.get(view_id)
            if view is None:
                return None
            view.last_access = now
            return view

    def create_view(self, *, dataset_id: str, frame: str, filter_expr: str) -> ViewHandle:
        current_id = self.current_dataset_id()
        if dataset_id != current_id:
            raise DatasetChangedError(current_id)

        try:
            obs_indices = self._client.compute_view_indices(filter_expr)
        except ValueError as e:
            raise InvalidFilterError(str(e))
        except RuntimeError as e:
            msg = str(e) or "No data in memory"
            if "no data" in msg.lower():
                raise NoDataInMemoryError(msg)
            raise
        now = time.time()
        view_id = f"view_{uuid.uuid4().hex}"
        view = ViewHandle(
            view_id=view_id,
            dataset_id=current_id,
            frame=frame,
            filter_expr=filter_expr,
            obs_indices=obs_indices,
            filtered_n=len(obs_indices),
            created_at=now,
            last_access=now,
        )
        with self._lock:
            self._evict_expired_locked(now)
            self._views[view_id] = view
        return view

    def delete_view(self, view_id: str) -> bool:
        with self._lock:
            return self._views.pop(view_id, None) is not None

    def validate_token(self, header_value: str | None) -> bool:
        if not header_value:
            return False
        if not header_value.startswith("Bearer "):
            return False
        token = header_value[len("Bearer ") :].strip()
        with self._lock:
            self._ensure_token()
            if self._token is None:
                return False
            if time.time() * 1000 >= self._expires_at:
                return False
            return secrets.compare_digest(token, self._token)

    def limits(self) -> tuple[int, int, int, int]:
        return self._max_limit, self._max_vars, self._max_chars, self._max_request_bytes

    def _ensure_token(self) -> None:
        now_ms = int(time.time() * 1000)
        if self._token is None or now_ms >= self._expires_at:
            self._token = secrets.token_urlsafe(32)
            self._expires_at = int((time.time() + self._token_ttl_s) * 1000)

    def _evict_expired_locked(self, now: float) -> None:
        expired: list[str] = []
        for key, view in self._views.items():
            if now - view.last_access >= self._view_ttl_s:
                expired.append(key)
        for key in expired:
            self._views.pop(key, None)

    def _ensure_http_server(self) -> None:
        with self._lock:
            if self._httpd is not None:
                return

            manager = self

            class Handler(BaseHTTPRequestHandler):

                def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                    data = json.dumps(payload).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

                def _send_binary(self, status: int, data: bytes, content_type: str) -> None:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

                def _error(self, status: int, code: str, message: str, *, stata_rc: int | None = None) -> None:
                    body: dict[str, Any] = {"error": {"code": code, "message": message}}
                    if stata_rc is not None:
                        body["error"]["stataRc"] = stata_rc
                    self._send_json(status, body)

                def _require_auth(self) -> bool:
                    if manager.validate_token(self.headers.get("Authorization")):
                        return True
                    self._error(401, "auth_failed", "Unauthorized")
                    return False

                def _read_json(self) -> dict[str, Any] | None:
                    max_limit, max_vars, max_chars, max_bytes = manager.limits()
                    _ = (max_limit, max_vars, max_chars)

                    length = int(self.headers.get("Content-Length", "0") or "0")
                    if length <= 0:
                        return {}
                    if length > max_bytes:
                        self._error(400, "request_too_large", "Request too large")
                        return None
                    raw = self.rfile.read(length)
                    try:
                        parsed = json.loads(raw.decode("utf-8"))
                    except Exception:
                        self._error(400, "invalid_request", "Invalid JSON")
                        return None
                    if not isinstance(parsed, dict):
                        self._error(400, "invalid_request", "Expected JSON object")
                        return None
                    return parsed

                def do_GET(self) -> None:
                    if not self._require_auth():
                        return

                    if self.path == "/v1/dataset":
                        try:
                            state = manager._client.get_dataset_state()
                            dataset_id = manager.current_dataset_id()
                            self._send_json(
                                200,
                                {
                                    "dataset": {
                                        "id": dataset_id,
                                        "frame": state.get("frame"),
                                        "n": state.get("n"),
                                        "k": state.get("k"),
                                        "changed": state.get("changed"),
                                    }
                                },
                            )
                            return
                        except NoDataInMemoryError as e:
                            self._error(400, "no_data_in_memory", str(e), stata_rc=e.stata_rc)
                            return
                        except Exception as e:
                            self._error(500, "internal_error", str(e))
                            return

                    if self.path == "/v1/vars":
                        try:
                            state = manager._client.get_dataset_state()
                            dataset_id = manager.current_dataset_id()
                            variables = manager._client.list_variables_rich()
                            self._send_json(
                                200,
                                {
                                    "dataset": {"id": dataset_id, "frame": state.get("frame")},
                                    "variables": variables,
                                },
                            )
                            return
                        except NoDataInMemoryError as e:
                            self._error(400, "no_data_in_memory", str(e), stata_rc=e.stata_rc)
                            return
                        except Exception as e:
                            self._error(500, "internal_error", str(e))
                            return

                    self._error(404, "not_found", "Not found")

                def do_POST(self) -> None:
                    if not self._require_auth():
                        return


                    if self.path == "/v1/arrow":
                        body = self._read_json()
                        if body is None:
                            return
                        try:
                            resp_bytes = handle_arrow_request(manager, body, view_id=None)
                            self._send_binary(200, resp_bytes, "application/vnd.apache.arrow.stream")
                            return
                        except HTTPError as e:
                            self._error(e.status, e.code, e.message, stata_rc=e.stata_rc)
                            return
                        except Exception as e:
                            self._error(500, "internal_error", str(e))
                            return

                    if self.path == "/v1/page":
                        body = self._read_json()
                        if body is None:
                            return
                        # Debug logging to diagnose limit parameter issues
                        import sys
                        print(f"[DEBUG] /v1/page request body: {body}", file=sys.stderr, flush=True)
                        print(f"[DEBUG] limit value: {body.get('limit')!r} (type: {type(body.get('limit')).__name__})", file=sys.stderr, flush=True)
                        try:
                            resp = handle_page_request(manager, body, view_id=None)
                            self._send_json(200, resp)
                            return
                        except HTTPError as e:
                            print(f"[DEBUG] HTTPError: {e.code} - {e.message}", file=sys.stderr, flush=True)
                            self._error(e.status, e.code, e.message, stata_rc=e.stata_rc)
                            return
                        except Exception as e:
                            self._error(500, "internal_error", str(e))
                            return

                    if self.path == "/v1/views":
                        body = self._read_json()
                        if body is None:
                            return
                        dataset_id = str(body.get("datasetId", ""))
                        frame = str(body.get("frame", "default"))
                        filter_expr = str(body.get("filterExpr", ""))
                        if not dataset_id or not filter_expr:
                            self._error(400, "invalid_request", "datasetId and filterExpr are required")
                            return
                        try:
                            view = manager.create_view(dataset_id=dataset_id, frame=frame, filter_expr=filter_expr)
                            self._send_json(
                                200,
                                {
                                    "dataset": {"id": view.dataset_id, "frame": view.frame},
                                    "view": {"id": view.view_id, "filteredN": view.filtered_n},
                                },
                            )
                            return
                        except DatasetChangedError as e:
                            self._error(409, "dataset_changed", "Dataset changed")
                            return
                        except ValueError as e:
                            self._error(400, "invalid_filter", str(e))
                            return
                        except RuntimeError as e:
                            msg = str(e) or "No data in memory"
                            if "no data" in msg.lower():
                                self._error(400, "no_data_in_memory", msg)
                                return
                            self._error(500, "internal_error", msg)
                            return
                        except Exception as e:
                            self._error(500, "internal_error", str(e))
                            return

                    if self.path.startswith("/v1/views/") and self.path.endswith("/page"):
                        parts = self.path.split("/")
                        if len(parts) != 5:
                            self._error(404, "not_found", "Not found")
                            return
                        view_id = parts[3]
                        body = self._read_json()
                        if body is None:
                            return
                        # Debug logging to diagnose limit parameter issues
                        import sys
                        print(f"[DEBUG] /v1/views/{view_id}/page request body: {body}", file=sys.stderr, flush=True)
                        print(f"[DEBUG] limit value: {body.get('limit')!r} (type: {type(body.get('limit')).__name__})", file=sys.stderr, flush=True)
                        try:
                            resp = handle_page_request(manager, body, view_id=view_id)
                            self._send_json(200, resp)
                            return
                        except HTTPError as e:
                            print(f"[DEBUG] HTTPError: {e.code} - {e.message}", file=sys.stderr, flush=True)
                            self._error(e.status, e.code, e.message, stata_rc=e.stata_rc)
                            return
                        except Exception as e:
                            self._error(500, "internal_error", str(e))
                            return

                    if self.path.startswith("/v1/views/") and self.path.endswith("/arrow"):
                        parts = self.path.split("/")
                        if len(parts) != 5:
                            self._error(404, "not_found", "Not found")
                            return
                        view_id = parts[3]
                        body = self._read_json()
                        if body is None:
                            return
                        try:
                            resp_bytes = handle_arrow_request(manager, body, view_id=view_id)
                            self._send_binary(200, resp_bytes, "application/vnd.apache.arrow.stream")
                            return
                        except HTTPError as e:
                            self._error(e.status, e.code, e.message, stata_rc=e.stata_rc)
                            return
                        except Exception as e:
                            self._error(500, "internal_error", str(e))
                            return

                    if self.path == "/v1/filters/validate":
                        body = self._read_json()
                        if body is None:
                            return
                        filter_expr = str(body.get("filterExpr", ""))
                        if not filter_expr:
                            self._error(400, "invalid_request", "filterExpr is required")
                            return
                        try:
                            manager._client.validate_filter_expr(filter_expr)
                            self._send_json(200, {"ok": True})
                            return
                        except ValueError as e:
                            self._error(400, "invalid_filter", str(e))
                            return
                        except RuntimeError as e:
                            msg = str(e) or "No data in memory"
                            if "no data" in msg.lower():
                                self._error(400, "no_data_in_memory", msg)
                                return
                            self._error(500, "internal_error", msg)
                            return
                        except Exception as e:
                            self._error(500, "internal_error", str(e))
                            return

                    self._error(404, "not_found", "Not found")

                def do_DELETE(self) -> None:
                    if not self._require_auth():
                        return

                    if self.path.startswith("/v1/views/"):
                        parts = self.path.split("/")
                        if len(parts) != 4:
                            self._error(404, "not_found", "Not found")
                            return
                        view_id = parts[3]
                        if manager.delete_view(view_id):
                            self._send_json(200, {"ok": True})
                        else:
                            self._error(404, "not_found", "Not found")
                        return

                    self._error(404, "not_found", "Not found")

                def log_message(self, format: str, *args: Any) -> None:
                    return

            httpd = ThreadingHTTPServer((self._host, self._port), Handler)
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            self._httpd = httpd
            self._thread = t


class HTTPError(Exception):
    def __init__(self, status: int, code: str, message: str, *, stata_rc: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.stata_rc = stata_rc


class DatasetChangedError(Exception):
    def __init__(self, current_dataset_id: str):
        super().__init__("dataset_changed")
        self.current_dataset_id = current_dataset_id


class NoDataInMemoryError(Exception):
    def __init__(self, message: str = "No data in memory", *, stata_rc: int | None = None):
        super().__init__(message)
        self.stata_rc = stata_rc


class InvalidFilterError(Exception):
    def __init__(self, message: str, *, stata_rc: int | None = None):
        super().__init__(message)
        self.message = message
        self.stata_rc = stata_rc


def handle_page_request(manager: UIChannelManager, body: dict[str, Any], *, view_id: str | None) -> dict[str, Any]:
    max_limit, max_vars, max_chars, _ = manager.limits()

    if view_id is None:
        dataset_id = str(body.get("datasetId", ""))
        frame = str(body.get("frame", "default"))
    else:
        view = manager.get_view(view_id)
        if view is None:
            raise HTTPError(404, "not_found", "View not found")
        dataset_id = view.dataset_id
        frame = view.frame

    # Parse offset (default 0 is valid since offset >= 0)
    try:
        offset = int(body.get("offset") or 0)
    except (ValueError, TypeError) as e:
        raise HTTPError(400, "invalid_request", f"offset must be a valid integer, got: {body.get('offset')!r}")

    # Parse limit (no default - must be explicitly provided)
    limit_raw = body.get("limit")
    if limit_raw is None:
        raise HTTPError(400, "invalid_request", "limit is required")
    try:
        limit = int(limit_raw)
    except (ValueError, TypeError) as e:
        raise HTTPError(400, "invalid_request", f"limit must be a valid integer, got: {limit_raw!r}")

    vars_req = body.get("vars", [])
    include_obs_no = bool(body.get("includeObsNo", False))

    # Parse sortBy parameter
    sort_by = body.get("sortBy", [])
    if sort_by is not None and not isinstance(sort_by, list):
        raise HTTPError(400, "invalid_request", f"sortBy must be an array, got: {type(sort_by).__name__}")
    if sort_by and not all(isinstance(s, str) for s in sort_by):
        raise HTTPError(400, "invalid_request", "sortBy must be an array of strings")

    # Parse maxChars
    max_chars_raw = body.get("maxChars", max_chars)
    try:
        max_chars_req = int(max_chars_raw or max_chars)
    except (ValueError, TypeError) as e:
        raise HTTPError(400, "invalid_request", f"maxChars must be a valid integer, got: {max_chars_raw!r}")

    if offset < 0:
        raise HTTPError(400, "invalid_request", f"offset must be >= 0, got: {offset}")
    if limit <= 0:
        raise HTTPError(400, "invalid_request", f"limit must be > 0, got: {limit}")
    if limit > max_limit:
        raise HTTPError(400, "request_too_large", f"limit must be <= {max_limit}")
    if max_chars_req <= 0:
        raise HTTPError(400, "invalid_request", "maxChars must be > 0")
    if max_chars_req > max_chars:
        raise HTTPError(400, "request_too_large", f"maxChars must be <= {max_chars}")

    if not isinstance(vars_req, list) or not all(isinstance(v, str) for v in vars_req):
        raise HTTPError(400, "invalid_request", "vars must be a list of strings")
    if len(vars_req) > max_vars:
        raise HTTPError(400, "request_too_large", f"vars length must be <= {max_vars}")

    current_id = manager.current_dataset_id()
    if dataset_id != current_id:
        raise HTTPError(409, "dataset_changed", "Dataset changed")

    if view_id is None:
        obs_indices = None
        filtered_n: int | None = None
    else:
        assert view is not None
        obs_indices = view.obs_indices
        filtered_n = view.filtered_n

    try:
        # Apply sorting if requested
        if sort_by:
            try:
                manager._client.apply_sort(sort_by)
                # If sorting with a filtered view, re-compute indices after sort
                if view_id is not None:
                    assert view is not None
                    obs_indices = manager._client.compute_view_indices(view.filter_expr)
                    filtered_n = len(obs_indices)
            except ValueError as e:
                raise HTTPError(400, "invalid_request", f"Invalid sort specification: {e}")
            except RuntimeError as e:
                raise HTTPError(500, "internal_error", f"Failed to apply sort: {e}")

        dataset_state = manager._client.get_dataset_state()
        page = manager._client.get_page(
            offset=offset,
            limit=limit,
            vars=vars_req,
            include_obs_no=include_obs_no,
            max_chars=max_chars_req,
            obs_indices=obs_indices,
        )
    except HTTPError:
        # Re-raise HTTPError exceptions as-is
        raise
    except RuntimeError as e:
        # StataClient uses RuntimeError("No data in memory") for empty dataset.
        msg = str(e) or "No data in memory"
        if "no data" in msg.lower():
            raise HTTPError(400, "no_data_in_memory", msg)
        raise HTTPError(500, "internal_error", msg)
    except ValueError as e:
        msg = str(e)
        if msg.lower().startswith("invalid variable"):
            raise HTTPError(400, "invalid_variable", msg)
        raise HTTPError(400, "invalid_request", msg)
    except Exception as e:
        raise HTTPError(500, "internal_error", str(e))

    view_obj: dict[str, Any] = {
        "offset": offset,
        "limit": limit,
        "returned": page["returned"],
        "filteredN": filtered_n,
    }
    if view_id is not None:
        view_obj["viewId"] = view_id

    return {
        "dataset": {
            "id": current_id,
            "frame": dataset_state.get("frame"),
            "n": dataset_state.get("n"),
            "k": dataset_state.get("k"),
        },
        "view": view_obj,
        "vars": page["vars"],
        "rows": page["rows"],
        "display": {
            "maxChars": max_chars_req,
            "truncatedCells": page["truncated_cells"],
            "missing": ".",
        },
    }


def handle_arrow_request(manager: UIChannelManager, body: dict[str, Any], *, view_id: str | None) -> bytes:
    max_limit, max_vars, max_chars, _ = manager.limits()
    # Use the specific Arrow limit instead of the general UI page limit
    chunk_limit = getattr(manager, "_max_arrow_limit", 1_000_000)

    if view_id is None:
        dataset_id = str(body.get("datasetId", ""))
        frame = str(body.get("frame", "default"))
    else:
        view = manager.get_view(view_id)
        if view is None:
            raise HTTPError(404, "not_found", "View not found")
        dataset_id = view.dataset_id
        frame = view.frame

    # Parse offset (default 0)
    try:
        offset = int(body.get("offset") or 0)
    except (ValueError, TypeError):
        raise HTTPError(400, "invalid_request", "offset must be a valid integer")

    # Parse limit (required)
    limit_raw = body.get("limit")
    if limit_raw is None:
        # Default to the max arrow limit if not specified? 
        # The previous code required it. Let's keep it required but allow large values.
        raise HTTPError(400, "invalid_request", "limit is required")
    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        raise HTTPError(400, "invalid_request", "limit must be a valid integer")

    vars_req = body.get("vars", [])
    include_obs_no = bool(body.get("includeObsNo", False))
    sort_by = body.get("sortBy", [])

    if offset < 0:
        raise HTTPError(400, "invalid_request", "offset must be >= 0")
    if limit <= 0:
        raise HTTPError(400, "invalid_request", "limit must be > 0")
    # Arrow streams are efficient, but we still respect a (much larger) max limit
    if limit > chunk_limit:
        raise HTTPError(400, "request_too_large", f"limit must be <= {chunk_limit}")

    if not isinstance(vars_req, list) or not all(isinstance(v, str) for v in vars_req):
        raise HTTPError(400, "invalid_request", "vars must be a list of strings")
    if len(vars_req) > max_vars:
        raise HTTPError(400, "request_too_large", f"vars length must be <= {max_vars}")

    current_id = manager.current_dataset_id()
    if dataset_id != current_id:
        raise HTTPError(409, "dataset_changed", "Dataset changed")

    if view_id is None:
        obs_indices = None
    else:
        assert view is not None
        obs_indices = view.obs_indices

    try:
        # Apply sorting if requested
        if sort_by:
            if not isinstance(sort_by, list) or not all(isinstance(s, str) for s in sort_by):
                raise HTTPError(400, "invalid_request", "sortBy must be a list of strings")
            try:
                manager._client.apply_sort(sort_by)
                if view_id is not None:
                    # encapsulated re-computation if view is active
                    # Note: original code only does this for view_id is not None
                    # But if we sort global dataset, existing views might become invalid unless
                    # they rely on stable indices. Stata indices change on sort.
                    # The current implementation of create_view computes indices once.
                    # If we sort, those indices point to different rows! 
                    # The original code handles this by re-computing view indices on sort.
                    assert view is not None
                    obs_indices = manager._client.compute_view_indices(view.filter_expr)
            except ValueError as e:
                raise HTTPError(400, "invalid_request", f"Invalid sort: {e}")
            except RuntimeError as e:
                raise HTTPError(500, "internal_error", f"Sort failed: {e}")

        arrow_bytes = manager._client.get_arrow_stream(
            offset=offset,
            limit=limit,
            vars=vars_req,
            include_obs_no=include_obs_no,
            obs_indices=obs_indices,
        )
        return arrow_bytes

    except RuntimeError as e:
        msg = str(e) or "No data in memory"
        if "no data" in msg.lower():
            raise HTTPError(400, "no_data_in_memory", msg)
        raise HTTPError(500, "internal_error", msg)
    except ValueError as e:
        msg = str(e)
        if "invalid variable" in msg.lower():
            raise HTTPError(400, "invalid_variable", msg)
        raise HTTPError(400, "invalid_request", msg)
    except Exception as e:
        raise HTTPError(500, "internal_error", str(e))

