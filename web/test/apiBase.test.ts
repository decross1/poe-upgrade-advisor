/**
 * TASK-202 readiness (issue #60): apiBase is the one-line mock → skeleton
 * switch. These tests pin the contract default against BOTH the contract text
 * and the generated client's built-in default (drift = contract changed;
 * regenerate, never hand-patch) and cover the override/apply mechanics.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OpenAPI } from "../src/generated/core/OpenAPI";
import { CONTRACT_API_BASE, configureApiClient, resolveApiBase } from "../src/lib/apiBase";

const REPO_ROOT = join(import.meta.dirname, "..", "..");

describe("apiBase — the one-line mock→skeleton switch (issue #60)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    OpenAPI.BASE = CONTRACT_API_BASE;
  });

  it("contract default matches contracts/openapi.yaml servers[0].url", () => {
    const yaml = readFileSync(join(REPO_ROOT, "contracts", "openapi.yaml"), "utf8");
    const serversUrl = yaml.match(/servers:\s*\n\s*-\s*url:\s*(\S+)/)?.[1];
    expect(serversUrl).toBe(CONTRACT_API_BASE);
  });

  it("contract default matches the generated client's built-in default", () => {
    const generated = readFileSync(
      join(import.meta.dirname, "..", "src", "generated", "core", "OpenAPI.ts"),
      "utf8",
    );
    expect(generated).toContain(`BASE: '${CONTRACT_API_BASE}'`);
  });

  it("no override (or blank) resolves to the contract default", () => {
    expect(resolveApiBase(undefined)).toBe(CONTRACT_API_BASE);
    expect(resolveApiBase("")).toBe(CONTRACT_API_BASE);
    expect(resolveApiBase("   ")).toBe(CONTRACT_API_BASE);
  });

  it("explicit override wins and is trimmed", () => {
    expect(resolveApiBase("  http://127.0.0.1:48001/api/v0  ")).toBe(
      "http://127.0.0.1:48001/api/v0",
    );
  });

  it("VITE_API_BASE_URL env var drives the default resolution", () => {
    vi.stubEnv("VITE_API_BASE_URL", "http://127.0.0.1:48003/api/v0");
    expect(resolveApiBase()).toBe("http://127.0.0.1:48003/api/v0");
  });

  it("configureApiClient retargets the generated client and reports the active URL", () => {
    const active = configureApiClient("http://127.0.0.1:48002/api/v0");
    expect(active).toBe("http://127.0.0.1:48002/api/v0");
    expect(OpenAPI.BASE).toBe(active);
    // Default path restores the contract address.
    expect(configureApiClient()).toBe(CONTRACT_API_BASE);
  });
});
