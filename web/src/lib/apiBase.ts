/// <reference types="vite/client" />
/**
 * TASK-202 readiness (issue #60): the ONE hand-written place that decides
 * which API server the generated client talks to. Everything else imports the
 * generated DefaultService and inherits this choice (OpenAPI is a module
 * singleton).
 *
 * Default is the contract address (contracts/openapi.yaml servers[0].url) —
 * asserted against the contract text and against the generated client's
 * built-in default by test/apiBase.test.ts. If those assertions drift, the
 * contract changed: regenerate the client (PM-owned contract flow), never
 * hand-patch either side.
 *
 * The mock ↔ real-server switch is ONE LINE, no generated-code edits:
 * create web/.env.local with `VITE_API_BASE_URL=http://127.0.0.1:<port>/api/v0`
 * (vite inlines VITE_* vars at dev/build time). With no override at all, the
 * mock and the real server share the contract address, so the switch is: stop
 * one, start the other — zero web changes.
 */
import { OpenAPI } from "../generated/core/OpenAPI";

export const CONTRACT_API_BASE = "http://127.0.0.1:47791/api/v0";

/** Base URL the generated client should use: env override, else contract. */
export function resolveApiBase(
  override: string | undefined = import.meta.env.VITE_API_BASE_URL,
): string {
  const trimmed = override?.trim();
  return trimmed ? trimmed : CONTRACT_API_BASE;
}

/**
 * Point the generated client at `base` (default: resolveApiBase()) and return
 * the URL now in effect. Called once at app entry (main.tsx); tests use it to
 * retarget at an ephemeral server and to restore the default afterwards.
 */
export function configureApiClient(base: string = resolveApiBase()): string {
  OpenAPI.BASE = base;
  return OpenAPI.BASE;
}
