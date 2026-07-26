'use strict';
/*
 * Electron variant of the verdict-card overlay benchmark.
 *
 * Speaks the stack-neutral bench protocol (../README.md):
 *   stdin : {"cmd":"render","seq":N,"fixture_name":"upgrade"} | {"cmd":"quit"}
 *   stdout: {"bench":"cold_start","seq":0,...} | {"bench":"render",...}
 *
 * seq 0 is the cold-start paint: it renders the first card immediately after
 * load (no clipboard read). seq > 0 performs a REAL platform clipboard read
 * before rendering, mirroring the production hotkey path (Doctrine S1:
 * clipboard is the only game input; this bench never touches any game).
 */
const { app, BrowserWindow, ipcMain, clipboard } = require('electron');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const HEADLESS = process.env.BENCH_HEADLESS === '1';
const FIXTURES_DIR =
  process.env.BENCH_FIXTURES_DIR || path.resolve(__dirname, '..', 'fixtures');
const CARD_URL =
  'file://' + path.resolve(__dirname, '..', 'shared', 'card.html');

const tMainStart = performance.now();

// Headless runs (no display server) pass --ozone-platform=headless,
// --no-sandbox etc. via argv from run_bench.py: Chromium applies the ozone
// platform and sandbox decisions before any JS switch could take effect.
// Numbers stay comparable across stacks ONLY if every stack is run the same
// way on the same box; see ../README.md (Tauri has no headless mode, so
// cross-stack runs need a display, e.g. Xvfb or the real desktop).
if (HEADLESS) {
  app.commandLine.appendSwitch('disable-setuid-sandbox');
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

let win = null;
let loaded = false;
const pending = [];

function loadFixture(name) {
  const p = path.join(FIXTURES_DIR, `verdict_${name}.json`);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function dispatch(cmd) {
  let clipboardMs = null;
  if (cmd.seq > 0) {
    const c0 = performance.now();
    clipboard.readText(); // real platform clipboard read, content unused
    clipboardMs = performance.now() - c0;
  }
  const fixture = loadFixture(cmd.fixture_name || 'upgrade');
  win.webContents.send('bench-trigger', {
    seq: cmd.seq,
    fixture,
    clipboard_ms: clipboardMs,
  });
}

function onCmdLine(line) {
  let cmd;
  try {
    cmd = JSON.parse(line);
  } catch {
    return; // not a bench command; ignore
  }
  if (cmd.cmd === 'quit') {
    app.quit();
    return;
  }
  if (cmd.cmd === 'render') {
    if (loaded) dispatch(cmd);
    else pending.push(cmd);
  }
}

ipcMain.on('bench-report', (_event, msg) => {
  if (!msg || msg.type !== 'render') return;
  if (msg.seq === 0) {
    emit({
      bench: 'cold_start',
      seq: 0,
      pid: process.pid,
      main_to_paint_ms: performance.now() - tMainStart,
      render_ms: msg.render_ms,
    });
  } else {
    emit({
      bench: 'render',
      seq: msg.seq,
      clipboard_ms: msg.clipboard_ms,
      render_ms: msg.render_ms,
    });
  }
});

app.whenReady().then(() => {
  win = new BrowserWindow({
    width: 420,
    height: 260,
    useContentSize: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    show: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.setMenu(null);
  win.webContents.on('did-finish-load', () => {
    loaded = true;
    while (pending.length) dispatch(pending.shift());
  });
  win.loadURL(CARD_URL);
});

readline.createInterface({ input: process.stdin }).on('line', onCmdLine);
