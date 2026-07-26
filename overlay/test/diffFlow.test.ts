/**
 * Headless test of the hotkey → clipboard → POST /diff → state flow, using
 * the REAL generated client (web/src/generated) over REAL HTTP against an
 * in-test localhost server. This is the contract-conformance proof for the
 * shell's wiring: no hand-rolled fetch anywhere in the flow.
 *
 * Error fixtures need no JSON (RULING-20: status-code only, bare bodies).
 */
import http from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it } from "vitest";
import type { VerdictCard } from "../../web/src/lib/verdictFormat";
import { bindGeneratedDiff } from "../src/diffRequest";
import { createDiffFlow } from "../src/diffFlow";
import type { ShellState } from "../src/shellState";

import upgradeMappingJson from "../../contracts/fixtures/upgrade_mapping.json";
import sidegradeBossingJson from "../../contracts/fixtures/sidegrade_bossing.json";

const SAMPLE_ITEM_TEXT = "Item Class: Wands\r\nRarity: Rare\r\n...";

interface RecordedRequest {
  body: unknown;
}

interface StubServer {
  url: string;
  requests: RecordedRequest[];
  close: () => Promise<void>;
}

/** Programmable /diff responder: one handler decides status/body per request. */
async function startStubServer(
  handler: (body: any) => Promise<{ status: number; json?: unknown }> | { status: number; json?: unknown },
): Promise<StubServer> {
  const requests: RecordedRequest[] = [];
  const server = http.createServer((req, res) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", async () => {
      const body = JSON.parse(raw);
      requests.push({ body });
      const { status, json } = await handler(body);
      if (status === 200) {
        res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(json));
      } else {
        res.writeHead(status).end(); // RULING-20: bare error bodies
      }
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}/api/v0`,
    requests,
    close: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections(); // drop keep-alive sockets so vitest exits
        server.close(() => resolve());
      }),
  };
}

const servers: StubServer[] = [];
async function stub(
  handler: (body: any) => Promise<{ status: number; json?: unknown }> | { status: number; json?: unknown },
) {
  const s = await startStubServer(handler);
  servers.push(s);
  return s;
}
afterEach(async () => {
  await Promise.all(servers.splice(0).map((s) => s.close()));
});

function collectStates() {
  const states: ShellState[] = [];
  return { states, onState: (s: ShellState) => states.push(s) };
}

describe("diffFlow — hotkey → clipboard → generated-client /diff", () => {
  it("200: LOADING then VERDICT with the server's card; request body is item_text only", async () => {
    const server = await stub(() => ({ status: 200, json: upgradeMappingJson }));
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });

    await flow.onHotkey();

    expect(states).toEqual([
      { kind: "LOADING" },
      { kind: "VERDICT", card: upgradeMappingJson as VerdictCard },
    ]);
    // Spec §10: the overlay omits `preset` (build default) and sends no
    // overrides on the first diff of a session. Exactly one key.
    expect(server.requests).toHaveLength(1);
    expect(server.requests[0].body).toEqual({ item_text: SAMPLE_ITEM_TEXT });
    expect(Object.keys(server.requests[0].body as object)).toEqual(["item_text"]);
  });

  it("404 -> ERROR_NO_BUILD (status only, never the body)", async () => {
    const server = await stub(() => ({ status: 404 }));
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    await flow.onHotkey();
    expect(states).toEqual([{ kind: "LOADING" }, { kind: "ERROR_NO_BUILD" }]);
  });

  it("422 -> ERROR_UNPARSEABLE; empty clipboard is still sent (server judges, RULING-4)", async () => {
    const server = await stub((body) => (body.item_text.trim() === "" ? { status: 422 } : { status: 200, json: upgradeMappingJson }));
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => "   ",
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    await flow.onHotkey();
    expect(states).toEqual([{ kind: "LOADING" }, { kind: "ERROR_UNPARSEABLE" }]);
    expect(server.requests[0].body).toEqual({ item_text: "   " });
  });

  it("500 -> ERROR_UNAVAILABLE", async () => {
    const server = await stub(() => ({ status: 500 }));
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    await flow.onHotkey();
    expect(states).toEqual([{ kind: "LOADING" }, { kind: "ERROR_UNAVAILABLE" }]);
  });

  it("RULING-19: no response within the timeout -> ERROR_UNAVAILABLE", async () => {
    const server = await stub(() => new Promise(() => {}) as Promise<never>); // never responds
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
      timeoutMs: 50, // injected; production default is DIFF_TIMEOUT_MS (3000)
    });
    await flow.onHotkey();
    expect(states).toEqual([{ kind: "LOADING" }, { kind: "ERROR_UNAVAILABLE" }]);
  });

  it("connection refused (engine down) -> ERROR_UNAVAILABLE", async () => {
    const server = await stub(() => ({ status: 200, json: upgradeMappingJson }));
    const deadUrl = server.url;
    await server.close();
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(deadUrl),
      onState,
      timeoutMs: 2000,
    });
    await flow.onHotkey();
    expect(states).toEqual([{ kind: "LOADING" }, { kind: "ERROR_UNAVAILABLE" }]);
  });

  it("S2/§8.4: a newer keypress supersedes an in-flight request (late response dropped)", async () => {
    const server = await stub(async (body) => {
      if (body.item_text === "slow-item") {
        await new Promise((r) => setTimeout(r, 100));
        return { status: 200, json: sidegradeBossingJson };
      }
      return { status: 200, json: upgradeMappingJson };
    });
    const { states, onState } = collectStates();
    const clipboard = { text: "slow-item" };
    const flow = createDiffFlow({
      readClipboard: () => clipboard.text,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });

    const first = flow.onHotkey();
    clipboard.text = "fast-item";
    const second = flow.onHotkey();
    await Promise.all([first, second]);

    // Two explicit keypresses = exactly two server actions (S2 honored), but
    // only the freshest session may paint.
    expect(server.requests).toHaveLength(2);
    expect(states).toEqual([
      { kind: "LOADING" },
      { kind: "LOADING" },
      { kind: "VERDICT", card: upgradeMappingJson as VerdictCard },
    ]);
  });
});
