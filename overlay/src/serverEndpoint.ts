/**
 * Server endpoint resolution. Swapping the TASK-206 fixture mock for
 * TASK-202's real server is CONFIG-ONLY (issue #11 AC): set
 * POE_ADVISOR_SERVER_URL. The default mirrors servers[0].url in
 * contracts/openapi.yaml — test/serverEndpoint.test.ts pins it against the
 * contract text so drift fails loudly.
 *
 * These are process-level constants, NOT a settings surface (I1): nothing
 * here is rendered or user-facing in the overlay.
 */
export const CONTRACT_SERVER_URL = "http://127.0.0.1:47791/api/v0";

/** Vite dev-server default for the web app (Tier-2/3 deep links). */
export const DEFAULT_WEB_APP_URL = "http://127.0.0.1:5173";

export function resolveServerBaseUrl(env: NodeJS.ProcessEnv = process.env): string {
  return env.POE_ADVISOR_SERVER_URL ?? CONTRACT_SERVER_URL;
}

export function resolveWebAppUrl(env: NodeJS.ProcessEnv = process.env): string {
  return env.POE_ADVISOR_WEB_URL ?? DEFAULT_WEB_APP_URL;
}
