import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React 18: tells the renderer that act() is available in tests.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// vitest runs without global afterEach by default; unmount every render so
// queries (and snapshots) never see a previous test's DOM.
afterEach(() => cleanup());
