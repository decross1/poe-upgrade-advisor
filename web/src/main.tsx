import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./demo/App";
import { configureApiClient } from "./lib/apiBase";
import "./styles.css";

// Issue #60: the single network-target decision (env override or contract
// default) is applied once, before any component can issue a request.
configureApiClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
