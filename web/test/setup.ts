import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// vitest runs without global afterEach by default; unmount every render so
// queries (and snapshots) never see a previous test's DOM.
afterEach(() => cleanup());
