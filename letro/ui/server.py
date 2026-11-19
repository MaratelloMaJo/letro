"""Local, read-only audit workbench for LETRO.

The workbench is a demo and inspection surface, not part of the scored
environment. It serves the open records of the labelled train/dev episodes,
runs one of the four policy adapters, and shows the evaluator's terminal
metrics. It never serves ``truth.json`` and never accepts a path from a client:
episode directories come from ``episodes/index.json`` only.

Run ``python -m letro.ui`` and open http://127.0.0.1:8000.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..factory import env_from_episode
from ..generator import load_episode
from ..policies import (
    MarkAllPolicy,
    RandomExplorerPolicy,
    ReconciliationPolicy,
    ThoroughPolicy,
)
from ..tools import OpenStore, ToolError
from ..trajectory import TrajectoryRecorder, run_episode

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 64 * 1024
POLICIES = ("reconciliation", "thorough", "random_explorer", "mark_all")
TABLES = ("ledger", "invoices", "payments", "fx")


def _index() -> dict[str, Any]:
    path = ROOT / "episodes" / "index.json"
    if not path.exists():
        raise RuntimeError(
            "episodes/index.json is missing; run python scripts/build_episodes.py"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _entries(index: dict[str, Any]) -> list[dict[str, Any]]:
    return list(index.get("train", [])) + list(index.get("dev", []))


def _entry(index: dict[str, Any], episode_id: str) -> dict[str, Any] | None:
    for entry in _entries(index):
        if entry["episode_id"] == episode_id:
            return entry
    return None


def _load(entry: dict[str, Any]):
    return load_episode(ROOT / entry["directory"])


def _policy(name: str, episode: Any, seed: int):
    if name == "reconciliation":
        return ReconciliationPolicy()
    if name == "thorough":
        return ThoroughPolicy()
    if name == "random_explorer":
        return RandomExplorerPolicy(seed=seed)
    if name == "mark_all":
        return MarkAllPolicy()
    raise ValueError(f"unknown policy: {name}")


class _Capture:
    """Wrap a policy so the workbench can show the submitted findings."""

    def __init__(self, policy: Any):
        self.policy = policy
        self.name = getattr(policy, "name", "policy")
        self.actions: list[dict[str, Any]] = []

    def reset(self, observation: dict[str, Any], info: dict[str, Any]) -> None:
        self.policy.reset(observation, info)

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        action = self.policy.act(observation)
        self.actions.append(action)
        return action


def _summary(entry: dict[str, Any], episode: Any) -> dict[str, Any]:
    truth = episode.truth.get("issues", [])
    return {
        "episode_id": entry["episode_id"],
        "split": entry["split"],
        "seed": entry["seed"],
        "clean": bool(entry.get("clean")),
        "manifest": episode.manifest,
        "policy": episode.policy,
        "counts": {
            "ledger": len(episode.ledger),
            "invoices": len(episode.invoices),
            "payments": len(episode.payments),
            "fx": len(episode.fx),
        },
        "truth": {
            "count": len(truth),
            "types": sorted(issue["type"] for issue in truth),
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LETRO-UI/1.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:
        if args and str(args[0]).startswith("4"):
            sys.stderr.write("ui: " + (format % args) + "\n")

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
            "form-action 'self'",
        )
        self.end_headers()

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _text(self, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self._headers(status, content_type, len(body))
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            raise ValueError("request body is empty or too large")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _static(self, name: str) -> None:
        candidate = (STATIC / name).resolve()
        try:
            candidate.relative_to(STATIC.resolve())
        except ValueError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not candidate.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        body = candidate.read_bytes()
        kind = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "application/json"):
            kind += "; charset=utf-8"
        self._headers(HTTPStatus.OK, kind, len(body))
        self.wfile.write(body)

    # -- GET --------------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._static("index.html")
            return
        if path.startswith("/static/"):
            self._static(path[len("/static/") :])
            return
        if path == "/api/health":
            index = _index()
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "episodes": len(_entries(index)),
                    "schema_version": index.get("schema_version"),
                },
            )
            return
        if path == "/api/episodes":
            index = _index()
            self._json(
                HTTPStatus.OK,
                {
                    "schema_version": index.get("schema_version"),
                    "episodes": [
                        {
                            "episode_id": entry["episode_id"],
                            "split": entry["split"],
                            "seed": entry["seed"],
                            "clean": bool(entry.get("clean")),
                            "issues": len(entry.get("issues", [])),
                            "ledger_rows": entry.get("ledger_rows"),
                            "documents": entry.get("documents"),
                        }
                        for entry in _entries(index)
                    ],
                },
            )
            return

        parts = [item for item in path.split("/") if item]
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "episodes":
            index = _index()
            entry = _entry(index, parts[2])
            if entry is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown episode"})
                return
            episode = _load(entry)
            if len(parts) == 4 and parts[3] == "summary":
                self._json(HTTPStatus.OK, _summary(entry, episode))
                return
            if len(parts) == 4 and parts[3] == "records":
                query = parse_qs(parsed.query)
                table = (query.get("table") or ["ledger"])[0]
                if table not in TABLES:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "unknown table"})
                    return
                try:
                    cursor = int((query.get("cursor") or ["0"])[0])
                    limit = int((query.get("limit") or ["25"])[0])
                except ValueError:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "cursor and limit must be integers"})
                    return
                if limit < 1 or limit > 50 or cursor < 0:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "limit must be 1..50 and cursor non-negative"})
                    return
                store = OpenStore(episode.open_data())
                try:
                    page = store.list_records(table, cursor, limit)
                except ToolError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._json(HTTPStatus.OK, page)
                return
            if len(parts) == 4 and parts[3] == "record":
                query = parse_qs(parsed.query)
                table = (query.get("table") or [""])[0]
                record_id = (query.get("id") or [""])[0]
                if table not in TABLES or not record_id:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "table and id are required"})
                    return
                store = OpenStore(episode.open_data())
                try:
                    record = store.get_record(table, record_id)
                except ToolError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                    return
                self._json(HTTPStatus.OK, {"table": table, "record": record})
                return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    # -- POST -------------------------------------------------------------

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            body = self._body()
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        episode_id = body.get("episode_id")
        policy_name = body.get("policy", "reconciliation")
        if not isinstance(episode_id, str) or not isinstance(policy_name, str):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "episode_id and policy must be strings"})
            return
        if policy_name not in POLICIES:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "unknown policy"})
            return
        index = _index()
        entry = _entry(index, episode_id)
        if entry is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown episode"})
            return
        episode = _load(entry)
        env, evaluator = env_from_episode(episode, mode="eval")
        policy = _Capture(_policy(policy_name, episode, int(entry["seed"])))
        recorder = TrajectoryRecorder()
        started = time.perf_counter()
        result = run_episode(env, policy, recorder=recorder, evaluator=evaluator)
        elapsed = round((time.perf_counter() - started) * 1000.0, 1)
        report = evaluator.result()
        findings: list[dict[str, Any]] = []
        for action in reversed(policy.actions):
            if isinstance(action, dict) and action.get("type") == "submit":
                payload = action.get("findings") or {}
                if isinstance(payload, dict):
                    findings = list(payload.get("findings") or [])
                break
        metrics = {
            key: report.get(key)
            for key in ("tp", "fp", "fn", "precision", "recall", "f1", "reward")
        }
        self._json(
            HTTPStatus.OK,
            {
                "episode_id": episode_id,
                "split": entry["split"],
                "policy": policy_name,
                "steps": result.steps,
                "elapsed_ms": elapsed,
                "terminated": result.terminated,
                "truncated": result.truncated,
                "metrics": metrics,
                "truth": {
                    "count": len(episode.truth.get("issues", [])),
                    "types": sorted(
                        issue["type"] for issue in episode.truth.get("issues", [])
                    ),
                },
                "findings": findings,
            },
        )


def create_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m letro.ui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        _index()
    except RuntimeError as exc:
        print(exc)
        return 2
    server = create_server(args.host, args.port)
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}"
    print(f"LETRO audit workbench: {url}")
    print("read-only; labelled train/dev episodes only; Ctrl+C to stop")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
