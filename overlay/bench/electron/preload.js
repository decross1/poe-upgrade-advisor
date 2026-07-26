'use strict';
/* Bridges the sandboxed renderer to the bench protocol without exposing
 * nodeIntegration: renderer reports via __BENCH_REPORT__, host triggers
 * arrive as DOM CustomEvents (identical surface to the Tauri adapter in
 * shared/card.html). */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('__BENCH_REPORT__', (type, data) => {
  ipcRenderer.send('bench-report', Object.assign({ type }, data));
});

ipcRenderer.on('bench-trigger', (_event, payload) => {
  window.dispatchEvent(new CustomEvent('bench-trigger', { detail: payload }));
});
