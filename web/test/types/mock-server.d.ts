/**
 * Type shim so tests can import the TASK-206 fixture mock (plain ESM, no
 * types) under `tsc --noEmit`. Keep in sync with web/mock/server.mjs exports.
 */
declare module "*/mock/server.mjs" {
  import type { Server } from "node:http";

  export const CONTRACT_HOST: string;
  export const CONTRACT_PORT: number;
  export const CONTRACT_BASE_PATH: string;
  export const DEFAULT_FIXTURES_DIR: string;
  export function loadFixtures(dir?: string): Map<string, unknown>;
  export function route(
    body: unknown,
    fixtures: Map<string, unknown>,
  ): { status: number; card?: Record<string, unknown> };
  export function createMockServer(options?: { fixturesDir?: string }): Server;
}
