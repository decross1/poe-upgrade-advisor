#!/usr/bin/env python3
"""PoE Upgrade Advisor — MVP v0 launcher (TASK-208).

One process, zero dev tooling: serves the prebuilt web bundle and the local
diff API same-origin on the contract address (127.0.0.1:47791).

Same-origin is a requirement, not a nicety: the generated web client calls
``127.0.0.1:47791/api/v0`` directly (contracts/openapi.yaml servers[0]) and
the API sends no CORS headers, so the bundle and the API must share one
origin. This launcher therefore:

  1. runs the contract API (``server/``) in-process on an internal port, and
  2. serves ``web/`` statics on the contract port, proxying ``/api/v0/*``
     to (1) — the browser never sees the internal port.

Runtime deps: python3 + the server's own single dep (pyyaml); ``run.sh``
bootstraps both. Trust boundary is unchanged from server/README: everything
binds 127.0.0.1 only, no auth, no remote bind ever.
"""

from __future__ import annotations

import argparse
import http.client
import mimetypes
import platform
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
# Allow `import server` when this file runs as a script from the package root.
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"  # localhost trust boundary; never bind anything else
PUBLIC_PORT = 47791  # contracts/openapi.yaml servers[0] — the web client hardcodes it
API_PORT = 47991  # internal hop only; never opened in the browser
BASE_PATH = "/api/v0"
INDEX = "index.html"

# mimetypes is platform-db dependent; pin the bundle's actual types.
MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def build_api_server(
    port: int,
    calculator: object | None = None,
) -> ThreadingHTTPServer:
    """Construct the contract API exactly like server/__main__.py does.

    Keep in sync with server/__main__.py.
    """
    from server.app import ApiApplication, create_server
    from server.assumptions import AssumptionsEvaluator
    from server.calculator import PobCalculator

    app = ApiApplication(
        calculator or PobCalculator(ROOT),
        AssumptionsEvaluator(ROOT / "assumptions"),
    )
    return create_server(app, HOST, port)


def _mime(path: Path) -> str:
    if path.suffix.lower() in MIME_OVERRIDES:
        return MIME_OVERRIDES[path.suffix.lower()]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def make_public_handler(web_dir: Path, api_port: int) -> type[BaseHTTPRequestHandler]:
    web_root = web_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._route(None)

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("content-length", "0"))
                body = self.rfile.read(length) if length else None
            except (ValueError, OSError):
                self.send_error(400)
                return
            self._route(body)

        def _route(self, body: bytes | None) -> None:
            path = urlsplit(self.path).path
            if path == BASE_PATH or path.startswith(f"{BASE_PATH}/"):
                self._proxy(body)
            else:
                self._static(path)

        def _proxy(self, body: bytes | None) -> None:
            """Forward /api/v0/* verbatim to the in-process API server."""
            conn = http.client.HTTPConnection(HOST, api_port, timeout=10)
            headers = {"content-type": "application/json"} if body else {}
            try:
                conn.request(self.command, self.path, body=body, headers=headers)
                upstream = conn.getresponse()
                data = upstream.read()
            except OSError:
                self.send_error(502, "API server unreachable")
                return
            finally:
                conn.close()
            self.send_response(upstream.status)
            content_type = upstream.getheader("content-type")
            if content_type:
                self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _static(self, path: str) -> None:
            candidate = (web_root / path.lstrip("/")).resolve()
            # Traversal guard + SPA fallback: anything outside web_root or not
            # a real file serves the bundle's index (single-page app).
            if not candidate.is_file() or web_root not in candidate.parents:
                candidate = web_root / INDEX
            try:
                data = candidate.read_bytes()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("content-type", _mime(candidate))
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: object) -> None:
            # Keep the tester's console to launcher's own status lines.
            pass

    return Handler


def serve(
    web_dir: Path,
    port: int = PUBLIC_PORT,
    api_port: int = API_PORT,
    calculator: object | None = None,
) -> tuple[ThreadingHTTPServer, ThreadingHTTPServer]:
    """Start (public, api) servers; caller owns shutdown. Port 0 = ephemeral."""
    api_server = build_api_server(api_port, calculator)
    threading.Thread(target=api_server.serve_forever, daemon=True).start()
    # Read back the bound port so api_port=0 (ephemeral, used by tests) works.
    bound_api_port = api_server.server_address[1]
    public = ThreadingHTTPServer((HOST, port), make_public_handler(web_dir, bound_api_port))
    return public, api_server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=PUBLIC_PORT)
    parser.add_argument("--api-port", type=int, default=API_PORT)
    parser.add_argument("--web-dir", type=Path, default=ROOT / "web")
    parser.add_argument(
        "--open",
        action="store_true",
        help="open the app in the default browser once listening",
    )
    args = parser.parse_args()

    index = args.web_dir / INDEX
    if not index.is_file():
        sys.exit(f"error: {index} not found — run scripts/package_mvp.sh to build the bundle")

    try:
        public, api_server = serve(args.web_dir, args.port, args.api_port)
    except OSError as exc:
        sys.exit(
            f"error: cannot bind {HOST} ({exc}). Is the app already running? "
            "Close the other window first, or pick another --port."
        )
    except Exception as exc:
        # Engine-start failures (worker won't exec on this platform, vendored
        # tree missing) must be an honest dead stop, never a silent fallback
        # to canned verdicts (doctrine I5).
        from server.calculator import WorkerUnavailable

        if isinstance(exc, WorkerUnavailable):
            host_platform = f"{platform.system()} {platform.machine()}".strip()
            sys.exit(
                "error: the calculation engine could not start on this "
                f"machine ({exc}).\nNo verdict was produced. The bundled "
                f"runtime is missing or unsupported on {host_platform}. "
                "Re-download the app and report this in #poe if it continues."
            )
        raise
    url = f"http://{HOST}:{public.server_address[1]}/"
    print(f"PoE Upgrade Advisor (MVP v0) listening on {url}", flush=True)
    print("Ctrl+C to stop.", flush=True)
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        public.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        public.shutdown()
        api_server.shutdown()


if __name__ == "__main__":
    main()
