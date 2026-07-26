"""Smoke tests for the MVP v0 launcher (TASK-208).

Exercises the real server app (fixture calculator) through the launcher's
same-origin proxy on ephemeral ports — no npm, no network, no fixed ports.
The web bundle is replaced by a two-file stand-in; packaging of the real
bundle is covered by scripts/package_mvp.sh and the clean-room run recorded
on the PR.

The module is loaded by path (not `import packaging.launch`) because the
directory name collides with the PyPI `packaging` package in site-packages.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="server/assumptions.py requires pyyaml")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # for `import server`, mirroring launch.py

_spec = importlib.util.spec_from_file_location("mvp_launch", ROOT / "packaging" / "launch.py")
launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launch)


@pytest.fixture()
def stack(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<h1>mvp-stand-in</h1>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    public, api = launch.serve(web, port=0, api_port=0)
    port = public.server_address[1]
    import threading

    thread = threading.Thread(target=public.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    public.shutdown()
    api.shutdown()
    thread.join(timeout=5)


def _get(url: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry status
        return exc.code, exc.headers.get("content-type", ""), exc.read()


def _post(url: str, payload: dict) -> tuple[int, dict | None]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else None


def test_serves_index_at_root(stack):
    status, content_type, body = _get(f"{stack}/")
    assert status == 200
    assert content_type.startswith("text/html")
    assert b"mvp-stand-in" in body


def test_serves_bundle_asset_with_js_mime(stack):
    status, content_type, body = _get(f"{stack}/assets/app.js")
    assert status == 200
    assert content_type.startswith("text/javascript")
    assert b"console.log" in body


def test_traversal_falls_back_to_index(stack):
    status, _, body = _get(f"{stack}/../../pytest.ini")
    assert status == 200
    assert b"mvp-stand-in" in body
    assert b"pythonpath" not in body


def test_unknown_route_is_spa_fallback(stack):
    status, _, body = _get(f"{stack}/tier3/breakdown/d-whatever")
    assert status == 200
    assert b"mvp-stand-in" in body


def test_api_round_trip_through_proxy(stack):
    status, build = _post(
        f"{stack}/api/v0/build",
        {"pob_code": "@skill:Fireball;@tag:chill", "character_class": "Witch", "level": 90},
    )
    assert status == 200
    assert build["main_skill"]["name"] == "Fireball"

    item_text = (
        "Rarity: RARE\nDoom Wrap\n--------\n"
        "(launcher smoke test; fixture marker below)\n@fixture:upgrade_mapping"
    )
    status, verdict = _post(f"{stack}/api/v0/diff", {"item_text": item_text})
    assert status == 200
    assert verdict["verdict"] == "UPGRADE"
    assert "diff_id" in verdict

    status, _, _ = _get(f"{stack}/api/v0/build")
    assert status == 200


def test_api_404_propagates_through_proxy(stack):
    # No build imported on a fresh app: GET /build is a bare 404 (RULING-20).
    status, _, _ = _get(f"{stack}/api/v0/build")
    assert status == 404


# --- Windows launcher (run.bat) static contract ---------------------------
# run.bat is AUTHORED BLIND: this dev box has no Windows lane, so cmd.exe
# semantics (label/goto parsing, errorlevel flow) are verified here only
# statically. First real execution is the non-dev-box install test on
# issue #54 — do not check that box without it.


def test_run_bat_is_crlf_only():
    bat = (ROOT / "packaging" / "run.bat").read_bytes()
    assert bat, "run.bat missing"
    # cmd.exe misparses LF-only batch files that use labels/goto.
    assert b"\n" not in bat.replace(b"\r\n", b""), "run.bat must be CRLF-only"


def test_run_bat_mirrors_run_sh_contract():
    bat = (ROOT / "packaging" / "run.bat").read_text(encoding="ascii")
    sh = (ROOT / "packaging" / "run.sh").read_text(encoding="utf-8")
    # Same entrypoint, same --open passthrough, same one dependency spec.
    assert "packaging\\launch.py --open %*" in bat
    assert '.venv\\Scripts\\python.exe -m pip install --quiet --disable-pip-version-check "pyyaml>=6.0"' in bat
    for dep in ('"pyyaml>=6.0"',):
        assert dep in sh and dep in bat, "run.sh/run.bat dependency spec drift"
    # Prefers the python.org py launcher; plain python is only the fallback.
    assert 'set "PY=py -3"' in bat
    # Never touches a fixed port or remote host itself; launch.py owns that.
    assert "47791" not in bat and "http" not in bat.lower().replace("https://www.python.org", "")


def test_package_script_stages_all_launchers():
    script = (ROOT / "scripts" / "package_mvp.sh").read_text(encoding="utf-8")
    for artifact in ('"$STAGE/run.sh"', '"$STAGE/run.command"', '"$STAGE/run.bat"'):
        assert artifact in script, f"package_mvp.sh no longer stages {artifact}"
