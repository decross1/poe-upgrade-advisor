"""Smoke tests for the MVP v0 launcher (TASK-208).

Exercises the real server app through the launcher's same-origin proxy on
ephemeral ports — no native engine, npm, network, or fixed ports.
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

from server.calculator import EngineDiff, ImportedBuild, WorkerUnavailable

_spec = importlib.util.spec_from_file_location("mvp_launch", ROOT / "packaging" / "launch.py")
launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launch)


class SmokeCalculator:
    def import_build(self, pob_code):
        return ImportedBuild(
            "b-smoke",
            {
                "active_skills": [
                    {"name": "Fireball", "links": 6, "dps": 1, "tags": []}
                ],
                "allocated_keystone": None,
                "has_charge_generation": None,
                "has_trigger_setup": False,
            },
        )

    def configure_build(self, canonical_config):
        return {"base_class": "Witch", "ascendancy": "None", "level": 90}

    def diff(self, item_text, canonical_config):
        return EngineDiff(
            {
                "baseline": {"total_dps": 100, "ehp": 100},
                "candidate": {"total_dps": 110, "ehp": 101},
                "deltas": {"total_dps": 10, "ehp": 1},
                "slot": "Weapon 1",
                "breakdown_ref": "pob://calcs/Weapon 1",
            },
            4.3,
        )

    def close(self):
        return


@pytest.fixture()
def stack(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<h1>mvp-stand-in</h1>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    public, api = launch.serve(
        web, port=0, api_port=0, calculator=SmokeCalculator()
    )
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
        {"pob_code": "smoke"},
    )
    assert status == 200
    assert build["main_skill"]["name"] == "Fireball"

    item_text = "Rarity: RARE\nDoom Wrap\n--------\nlauncher smoke test"
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


def test_package_script_stages_real_engine():
    """The bundle must contain the real engine (server+engine+web, I5).

    A tester MUST get real PoB verdicts — never a silent fixture fallback —
    and MUST NOT need dev tooling (the Lua runtime ships prebuilt).
    """
    script = (ROOT / "scripts" / "package_mvp.sh").read_text(encoding="utf-8")
    # Worker entrypoint + the helpers server/calculator.py imports or shells.
    for artifact in ("engine/pobcalc", "engine/pobcalc.lua",
                     "engine/preset_config.py", "engine/timeless_cache.py"):
        assert artifact in script, f"package_mvp.sh no longer stages {artifact}"
    # Prebuilt pinned runtime ships (no cc/make/git on tester machines)...
    assert "engine/.runtime/bin" in script
    # ...but the local timeless-data cache must NOT ship (regenerated from
    # the vendored zips on first run; ~67M decompressed otherwise).
    assert "timeless-data" in script, "script must document the exclusion"
    assert "engine/.runtime/share engine/.runtime/manifest" in script
    # Vendored PoB source ships minus TreeData GUI sprites only.
    for exclude in ("src/TreeData/*.png", "src/TreeData/*.jpg",
                    "src/TreeData/*.webp", "src/TreeData/*/*.png",
                    "src/TreeData/*/*.jpg", "src/TreeData/*/*.webp"):
        assert exclude in script, f"TreeData sprite exclusion lost: {exclude}"
    assert "runtime/lua" in script  # headless lua libs still ship
    # Fixture-backed verdicts are gone from the tester artifact.
    assert "contracts/fixtures" not in script


def test_launch_exits_honestly_when_engine_unavailable(tmp_path, monkeypatch, capsys):
    """Unsupported platform => honest dead stop, no traceback, no fallback."""
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>mvp</h1>", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise WorkerUnavailable("unable to start pobcalc: exec format error")

    monkeypatch.setattr(launch, "serve", boom)
    monkeypatch.setattr(
        sys, "argv", ["launch.py", "--web-dir", str(web)]
    )
    with pytest.raises(SystemExit) as excinfo:
        launch.main()
    message = str(excinfo.value)
    assert "calculation engine could not start" in message
    assert "#poe" in message  # tells the tester where to report

    def boom_other(*_args, **_kwargs):
        raise ValueError("unrelated bug")

    monkeypatch.setattr(launch, "serve", boom_other)
    with pytest.raises(ValueError):
        launch.main()
