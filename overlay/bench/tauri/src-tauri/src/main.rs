//! Tauri v2 variant of the verdict-card overlay benchmark.
//!
//! Speaks the stack-neutral bench protocol (../../README.md):
//!   stdin : {"cmd":"render","seq":N,"fixture_name":"upgrade"} | {"cmd":"quit"}
//!   stdout: {"bench":"cold_start","seq":0,...} | {"bench":"render",...}
//!
//! seq 0 is the cold-start paint (no clipboard read). seq > 0 performs a real
//! platform clipboard read before rendering, mirroring the production hotkey
//! path (Doctrine S1: clipboard is the only game input).
//!
//! NOTE (honesty): this file could not be compiled on the arm64 CI box that
//! authored it (no Rust toolchain, no system webkit2gtk dev packages, no
//! display). It is intentionally small and uses only bog-standard Tauri v2
//! APIs, but the first `cargo build` on a provisioned box may need trivial
//! fixes. That is recorded in ADR-0004 and the follow-up issue.

use serde::Deserialize;
use serde_json::json;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Instant;
use tauri::{Emitter, Listener, Manager};
use tauri_plugin_clipboard::ClipboardExt;

#[derive(Deserialize)]
struct Cmd {
    cmd: String,
    seq: Option<u64>,
    fixture_name: Option<String>,
}

fn fixtures_dir() -> PathBuf {
    std::env::var("BENCH_FIXTURES_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../fixtures"))
}

fn emit_line(v: &serde_json::Value) {
    let stdout = std::io::stdout();
    let mut lock = stdout.lock();
    let _ = writeln!(lock, "{v}");
    let _ = lock.flush();
}

fn main() {
    let t_start = Instant::now();
    let renderer_ready = Arc::new(AtomicBool::new(false));
    let ready_for_listener = renderer_ready.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_clipboard::init())
        .setup(move |app| {
            // Renderer -> host: forward bench reports to stdout.
            app.listen("bench-report", move |event| {
                let v: serde_json::Value =
                    serde_json::from_str(event.payload()).unwrap_or_else(|_| json!({}));
                if v.get("type").and_then(|t| t.as_str()) != Some("render") {
                    return;
                }
                ready_for_listener.store(true, Ordering::SeqCst);
                let seq = v.get("seq").and_then(|s| s.as_u64()).unwrap_or(0);
                if seq == 0 {
                    emit_line(&json!({
                        "bench": "cold_start",
                        "seq": 0,
                        "pid": std::process::id(),
                        "main_to_paint_ms": t_start.elapsed().as_secs_f64() * 1000.0,
                        "render_ms": v.get("render_ms"),
                    }));
                } else {
                    emit_line(&json!({
                        "bench": "render",
                        "seq": seq,
                        "clipboard_ms": v.get("clipboard_ms"),
                        "render_ms": v.get("render_ms"),
                    }));
                }
            });

            // Host stdin -> renderer: triggers.
            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                let stdin = std::io::stdin();
                for line in BufReader::new(stdin).lines().map_while(Result::ok) {
                    let Ok(cmd) = serde_json::from_str::<Cmd>(&line) else {
                        continue;
                    };
                    match cmd.cmd.as_str() {
                        "quit" => app_handle.exit(0),
                        "render" => {
                            // Never emit before the webview has loaded and
                            // painted once, or the event is lost.
                            while !renderer_ready.load(Ordering::SeqCst) {
                                std::thread::sleep(std::time::Duration::from_millis(10));
                            }
                            let seq = cmd.seq.unwrap_or(0);
                            let mut clipboard_ms = serde_json::Value::Null;
                            if seq > 0 {
                                let c0 = Instant::now();
                                let _ = app_handle.clipboard().read_text();
                                clipboard_ms = json!(c0.elapsed().as_secs_f64() * 1000.0);
                            }
                            let name =
                                cmd.fixture_name.clone().unwrap_or_else(|| "upgrade".into());
                            let path = fixtures_dir().join(format!("verdict_{name}.json"));
                            let Ok(text) = std::fs::read_to_string(path) else {
                                continue;
                            };
                            let Ok(fixture) =
                                serde_json::from_str::<serde_json::Value>(&text)
                            else {
                                continue;
                            };
                            let _ = app_handle.emit_to(
                                "main",
                                "bench-trigger",
                                json!({
                                    "seq": seq,
                                    "fixture": fixture,
                                    "clipboard_ms": clipboard_ms,
                                }),
                            );
                        }
                        _ => {}
                    }
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running bench overlay");
}
