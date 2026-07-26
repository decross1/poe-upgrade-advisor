/**
 * The backend swap (fixture mock -> real server) must be config-only
 * (issue #11 AC): default = servers[0].url from contracts/openapi.yaml,
 * overridable via POE_ADVISOR_SERVER_URL. This test pins the default against
 * the contract text so drift between the two fails loudly.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { CONTRACT_SERVER_URL, resolveServerBaseUrl, resolveWebAppUrl, DEFAULT_WEB_APP_URL } from "../src/serverEndpoint";

const openapi = parse(readFileSync(path.resolve(__dirname, "../../contracts/openapi.yaml"), "utf8")) as {
  servers: { url: string }[];
};

describe("serverEndpoint", () => {
  it("default base URL equals servers[0].url in contracts/openapi.yaml", () => {
    expect(CONTRACT_SERVER_URL).toBe("http://127.0.0.1:47791/api/v0");
    expect(openapi.servers[0].url).toBe(CONTRACT_SERVER_URL);
  });

  it("defaults to the contract URL when no env override is set", () => {
    expect(resolveServerBaseUrl({})).toBe(CONTRACT_SERVER_URL);
  });

  it("POE_ADVISOR_SERVER_URL swaps the backend with zero code changes", () => {
    expect(resolveServerBaseUrl({ POE_ADVISOR_SERVER_URL: "http://127.0.0.1:9000/api/v0" })).toBe(
      "http://127.0.0.1:9000/api/v0",
    );
  });

  it("web-app deep-link base defaults to the vite dev server and is env-overridable", () => {
    expect(resolveWebAppUrl({})).toBe(DEFAULT_WEB_APP_URL);
    expect(resolveWebAppUrl({ POE_ADVISOR_WEB_URL: "http://127.0.0.1:4173" })).toBe("http://127.0.0.1:4173");
  });
});
