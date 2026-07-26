/**
 * Renderer entry. The renderer makes NO network calls (CSP in index.html:
 * connect-src 'none') — /diff lives in the main process; this side only
 * paints states pushed over the preload bridge.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ShellApp } from "./ShellApp";
// Shared card styles (single source: web). esbuild extracts this to
// dist/renderer.css; no font or network loads on the render path (≤50 ms).
import "../../../web/src/styles.css";
import "./overlay.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ShellApp />
  </StrictMode>,
);
