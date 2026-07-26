/**
 * TASK-204 acceptance: override round-trip, snapshot-tested — the REAL
 * generated client against the REAL TASK-206 fixture mock (web/mock/server.mjs)
 * on an ephemeral localhost port. One chip tap = one POST /diff; the mock's
 * deterministic `#ovr-<sha256[:12]>` diff_id suffix proves the exact overrides
 * payload the server received (RULING-16), accumulation proves RULING-17, and
 * the returned card becomes the session's rendered truth (§7.3).
 */
import { createHash } from "node:crypto";
import type { Server } from "node:http";
import type { AddressInfo } from "node:net";
import { useEffect } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { CONTRACT_BASE_PATH, createMockServer } from "../mock/server.mjs";
import { OpenAPI } from "../src/generated/core/OpenAPI";
import { SessionCard } from "../src/session/SessionCard";
import { useCardSession } from "../src/session/useCardSession";

const ITEM = "Rarity: RARE\nDoom Wrap\n@fixture:upgrade_mapping";

/** Deterministic diff_id suffix the mock mints for a given overrides array. */
function ovrSuffix(overrides: unknown): string {
  return `#ovr-${createHash("sha256").update(JSON.stringify(overrides)).digest("hex").slice(0, 12)}`;
}

const EO_FLIPPED = [{ assumption_id: "config.elemental_overload", value: false }];
const EO_AND_FLASKS = [...EO_FLIPPED, { assumption_id: "config.flasks_up", value: false }];
const FLASKS_ONLY = [{ assumption_id: "config.flasks_up", value: false }];

function detailsHref(container: HTMLElement): string {
  return container.querySelector(".details-link")?.getAttribute("href") ?? "";
}

function Harness() {
  const session = useCardSession(); // default: real generated DefaultService.diffItem
  useEffect(() => {
    session.evaluate(ITEM);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <SessionCard state={session.state} loadingVisible={session.loadingVisible} onTapChip={session.tapChip} />;
}

describe("override round-trip over real HTTP (I3, RULING-16/17)", () => {
  let server: Server;
  let savedBase: string;

  beforeAll(async () => {
    server = createMockServer();
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const { port } = server.address() as AddressInfo;
    savedBase = OpenAPI.BASE;
    OpenAPI.BASE = `http://127.0.0.1:${port}${CONTRACT_BASE_PATH}`;
  });

  afterAll(async () => {
    OpenAPI.BASE = savedBase;
    await new Promise<void>((resolve, reject) =>
      server.close((err) => (err ? reject(err) : resolve())),
    );
  });

  it("tap → POST /diff → fresh card; overrides accumulate; tap-again restores", async () => {
    const { container } = render(<Harness />);

    // Initial diff over HTTP: UPGRADE card from upgrade_mapping.json, pristine diff_id.
    await screen.findByText("UPGRADE");
    await screen.findByText("crit recently");
    expect(detailsHref(container)).toBe(`/breakdown/${encodeURIComponent("d-8f2c41a7")}`);

    // One tap: the request carried exactly EO_FLIPPED (proven by the suffix).
    fireEvent.click(screen.getByText("crit recently"));
    await waitFor(() => {
      expect(detailsHref(container)).toContain(encodeURIComponent(ovrSuffix(EO_FLIPPED)));
    });
    const overridden = container.querySelector(".chip--overridden");
    expect(overridden?.textContent).toContain("↺");
    expect(overridden?.textContent).toContain("crit recently");
    // Acceptance: the override round-trip is snapshot-tested.
    expect(container.querySelector(".verdict-card")).toMatchSnapshot();

    // Accumulation (RULING-17): the second tap's request carried BOTH entries.
    fireEvent.click(screen.getByText("flasks up"));
    await waitFor(() => {
      expect(detailsHref(container)).toContain(encodeURIComponent(ovrSuffix(EO_AND_FLASKS)));
    });
    expect(container.querySelectorAll(".chip--overridden")).toHaveLength(2);

    // Tap again to restore inference (§7.1): EO leaves the set, flasks stays.
    fireEvent.click(screen.getByText("crit recently"));
    await waitFor(() => {
      expect(detailsHref(container)).toContain(encodeURIComponent(ovrSuffix(FLASKS_ONLY)));
    });
    expect(container.querySelectorAll(".chip--overridden")).toHaveLength(1);
    expect(container.querySelector(".chip--overridden")?.textContent).toContain("flasks up");
  });
});
