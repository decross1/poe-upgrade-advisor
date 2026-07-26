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
import type { Assumption } from "../../web/src/lib/overrides";
import { RECOMPUTE_FAILED_MESSAGE } from "../../web/src/lib/session";
import type { VerdictCard } from "../../web/src/lib/verdictFormat";
import { bindGeneratedDiff } from "../src/diffRequest";
import { createDiffFlow } from "../src/diffFlow";
import type { ShellState } from "../src/shellState";

import upgradeMappingJson from "../../contracts/fixtures/upgrade_mapping.json";
import sidegradeBossingJson from "../../contracts/fixtures/sidegrade_bossing.json";

const SAMPLE_ITEM_TEXT = "Item Class: Wands\r\nRarity: Rare\r\n...";

const upgradeMapping = upgradeMappingJson as VerdictCard;

/** A chip exactly as the card rendered it (the tap payload, §7). */
function chip(card: VerdictCard, id: string): Assumption {
  const found = card.assumptions.find((a) => a.id === id);
  if (!found) throw new Error(`fixture ${card.diff_id} has no chip ${id}`);
  return found;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

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
      {
        kind: "VERDICT",
        card: upgradeMapping,
        appliedOverrides: [],
        transientMessage: null,
      },
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
      {
        kind: "VERDICT",
        card: upgradeMapping,
        appliedOverrides: [],
        transientMessage: null,
      },
    ]);
  });
});

describe("diffFlow — chip tap → one re-diff (I3/§7, issue #64)", () => {
  it("one boolean tap = exactly one POST with the full overrides payload + echoed preset", async () => {
    const server = await stub(() => ({ status: 200, json: upgradeMappingJson }));
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    await flow.onHotkey();
    await flow.onChipTap(chip(upgradeMapping, "config.elemental_overload"));

    expect(server.requests).toHaveLength(2); // hotkey + tap — never more (S2)
    expect(server.requests[1].body).toEqual({
      item_text: SAMPLE_ITEM_TEXT, // session item text, unchanged (§7)
      preset: "mapping", // echo of the last response's preset (§7)
      overrides: [{ assumption_id: "config.elemental_overload", value: false }],
    });
    expect(states).toEqual([
      { kind: "LOADING" },
      { kind: "VERDICT", card: upgradeMapping, appliedOverrides: [], transientMessage: null },
      {
        kind: "REDIFFING",
        card: upgradeMapping,
        appliedOverrides: [],
        pendingChipId: "config.elemental_overload",
      },
      {
        kind: "VERDICT",
        card: upgradeMapping,
        appliedOverrides: [{ assumption_id: "config.elemental_overload", value: false }],
        transientMessage: null,
      },
    ]);
  });

  it("RULING-17: overrides accumulate across taps (full set resent every re-diff)", async () => {
    const server = await stub(() => ({ status: 200, json: upgradeMappingJson }));
    const { onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    await flow.onHotkey();
    await flow.onChipTap(chip(upgradeMapping, "config.elemental_overload"));
    await flow.onChipTap(chip(upgradeMapping, "config.flasks_up"));

    expect(server.requests).toHaveLength(3);
    expect(server.requests[2].body).toEqual({
      item_text: SAMPLE_ITEM_TEXT,
      preset: "mapping",
      overrides: [
        { assumption_id: "config.elemental_overload", value: false },
        { assumption_id: "config.flasks_up", value: false },
      ],
    });
  });

  it("re-tapping an overridden chip restores inference (override removed from the full set)", async () => {
    const server = await stub(() => ({ status: 200, json: upgradeMappingJson }));
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    await flow.onHotkey();
    await flow.onChipTap(chip(upgradeMapping, "config.elemental_overload"));
    await flow.onChipTap(chip(upgradeMapping, "config.elemental_overload"));

    expect(server.requests).toHaveLength(3);
    expect(server.requests[2].body).toEqual({
      item_text: SAMPLE_ITEM_TEXT,
      preset: "mapping",
      overrides: [],
    });
    expect(states.at(-1)).toEqual({
      kind: "VERDICT",
      card: upgradeMapping,
      appliedOverrides: [],
      transientMessage: null,
    });
  });

  it("RULING-18: a new hotkey press clears overrides — next diff is item_text only", async () => {
    const server = await stub(() => ({ status: 200, json: upgradeMappingJson }));
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    await flow.onHotkey();
    await flow.onChipTap(chip(upgradeMapping, "config.elemental_overload"));
    await flow.onHotkey(); // new item = new session

    expect(server.requests).toHaveLength(3);
    expect(server.requests[2].body).toEqual({ item_text: SAMPLE_ITEM_TEXT });
    expect(states.at(-1)).toEqual({
      kind: "VERDICT",
      card: upgradeMapping,
      appliedOverrides: [],
      transientMessage: null,
    });
  });

  it("RULING-14: a display-only (non-boolean) chip tap is a no-op — NO request", async () => {
    const server = await stub(() => ({ status: 200, json: upgradeMappingJson }));
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    await flow.onHotkey();
    const before = states.length;
    await flow.onChipTap(chip(upgradeMapping, "main_skill.most_linked_highest_dps")); // string value

    expect(server.requests).toHaveLength(1);
    expect(states).toHaveLength(before); // no state churn either
  });

  it("a tap while the initial diff is in flight is a no-op — NO request (S2)", async () => {
    const server = await stub(async () => {
      await sleep(50);
      return { status: 200, json: upgradeMappingJson };
    });
    const { onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    const hotkey = flow.onHotkey();
    await flow.onChipTap(chip(upgradeMapping, "config.elemental_overload")); // LOADING phase
    await hotkey;

    expect(server.requests).toHaveLength(1);
  });

  it("RULING-21: a failed re-diff reverts and shows the transient sentence message, then restores", async () => {
    let calls = 0;
    const server = await stub(() => (++calls === 1 ? { status: 200, json: upgradeMappingJson } : { status: 500 }));
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
      transientMs: 20, // injected; production default is TRANSIENT_MESSAGE_MS (3000)
    });
    await flow.onHotkey();
    await flow.onChipTap(chip(upgradeMapping, "config.elemental_overload"));

    expect(server.requests).toHaveLength(2);
    expect(states.at(-1)).toEqual({
      kind: "VERDICT",
      card: upgradeMapping, // untouched card
      appliedOverrides: [], // mutation dropped
      transientMessage: RECOMPUTE_FAILED_MESSAGE,
    });

    await sleep(60); // transient window elapses → original sentence restored
    expect(states.at(-1)).toEqual({
      kind: "VERDICT",
      card: upgradeMapping,
      appliedOverrides: [],
      transientMessage: null,
    });
  });

  it("a re-diff timing out counts as failure (RULING-19/21): revert + transient message", async () => {
    let calls = 0;
    const server = await stub(() => {
      calls += 1;
      return calls === 1
        ? { status: 200, json: upgradeMappingJson }
        : (new Promise(() => {}) as Promise<never>); // re-diff never responds
    });
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
      timeoutMs: 50,
      transientMs: 20,
    });
    await flow.onHotkey();
    await flow.onChipTap(chip(upgradeMapping, "config.elemental_overload"));

    expect(states.at(-1)).toEqual({
      kind: "VERDICT",
      card: upgradeMapping,
      appliedOverrides: [],
      transientMessage: RECOMPUTE_FAILED_MESSAGE,
    });
  });

  it("§8.4: a hotkey during REDIFFING supersedes it — the late re-diff response is dropped", async () => {
    const server = await stub(async (body) => {
      if (Array.isArray(body.overrides) && body.overrides.length > 0) {
        await sleep(80); // slow re-diff
        return { status: 200, json: sidegradeBossingJson };
      }
      return { status: 200, json: upgradeMappingJson };
    });
    const { states, onState } = collectStates();
    const flow = createDiffFlow({
      readClipboard: () => SAMPLE_ITEM_TEXT,
      postDiff: bindGeneratedDiff(server.url),
      onState,
    });
    await flow.onHotkey();
    const rediff = flow.onChipTap(chip(upgradeMapping, "config.elemental_overload"));
    await flow.onHotkey(); // supersedes the in-flight re-diff
    await rediff;

    expect(server.requests).toHaveLength(3);
    expect(states).toEqual([
      { kind: "LOADING" },
      { kind: "VERDICT", card: upgradeMapping, appliedOverrides: [], transientMessage: null },
      {
        kind: "REDIFFING",
        card: upgradeMapping,
        appliedOverrides: [],
        pendingChipId: "config.elemental_overload",
      },
      { kind: "LOADING" },
      { kind: "VERDICT", card: upgradeMapping, appliedOverrides: [], transientMessage: null },
    ]); // the slow sidegrade re-diff never paints
  });
});
