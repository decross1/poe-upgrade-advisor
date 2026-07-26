/**
 * TASK-204 live re-diff UX (docs/specs/verdict_card.md §7/§8) — session hook +
 * SessionCard with an injected controllable diff function (no network; the
 * real-HTTP round trip is overrideRoundTrip.test.tsx). Covers: one tap = one
 * POST with accumulated overrides (RULING-16/17), REDIFFING (§8.3, snapshot
 * row 11), revert-on-failure + transient sentence (RULING-21), LOADING and
 * the three error panels (§8.1/8.2, snapshot row 10), and session clearing
 * on a new item (RULING-18).
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CancelablePromise } from "../src/generated/core/CancelablePromise";
import {
  DIFF_TIMEOUT_MS,
  LOADING_FLASH_GUARD_MS,
  RECOMPUTE_FAILED_MESSAGE,
  TRANSIENT_MESSAGE_MS,
  type DiffRequestBody,
} from "../src/lib/session";
import type { VerdictCard as VerdictCardData } from "../src/lib/verdictFormat";
import { SessionCard } from "../src/session/SessionCard";
import { useCardSession, type DiffFn } from "../src/session/useCardSession";

import upgradeMappingJson from "../../contracts/fixtures/upgrade_mapping.json";

const upgradeMapping = upgradeMappingJson as VerdictCardData;

const ITEM = "Rarity: RARE\nDoom Wrap\n@fixture:upgrade_mapping";
const OTHER_ITEM = "Rarity: RARE\nNew Item\n@fixture:sidegrade_bossing";

/** The upgrade card after the server confirmed `crit recently → false`. */
const rediffedCard: VerdictCardData = {
  ...upgradeMapping,
  diff_id: "d-8f2c41a7#ovr-0123456789ab",
  assumptions: upgradeMapping.assumptions.map((a) =>
    a.id === "config.elemental_overload" ? { ...a, value: false } : a,
  ),
};

interface Deferred {
  promise: CancelablePromise<VerdictCardData>;
  resolve: (card: VerdictCardData) => void;
  reject: (error: unknown) => void;
  cancelSpy: ReturnType<typeof vi.fn>;
}

function deferred(): Deferred {
  let resolve!: (card: VerdictCardData) => void;
  let reject!: (error: unknown) => void;
  const cancelSpy = vi.fn();
  const promise = new CancelablePromise<VerdictCardData>((res, rej, onCancel) => {
    resolve = res;
    reject = rej;
    onCancel(() => cancelSpy());
  });
  return { promise, resolve, reject, cancelSpy };
}

function fakeDiff() {
  const calls: { body: DiffRequestBody; deferred: Deferred }[] = [];
  const diff: DiffFn = (body) => {
    const d = deferred();
    calls.push({ body, deferred: d });
    return d.promise;
  };
  return { diff, calls };
}

/** Status-carrying error standing in for the generated client's ApiError. */
function httpError(status: number): Error {
  return Object.assign(new Error(`HTTP ${status}`), { status });
}

function Harness({ diff }: { diff: DiffFn }) {
  const session = useCardSession(diff);
  // One hotkey press per harness mount.
  useEffect(() => {
    session.evaluate(ITEM);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <>
      <SessionCard state={session.state} loadingVisible={session.loadingVisible} onTapChip={session.tapChip} />
      <button type="button" onClick={() => session.evaluate(OTHER_ITEM)}>
        new-item
      </button>
    </>
  );
}

/** Render + resolve the initial diff; ends in VERDICT with upgrade_mapping. */
async function renderVerdict(diff: DiffFn, calls: { body: DiffRequestBody; deferred: Deferred }[]) {
  const view = render(<Harness diff={diff} />);
  expect(calls).toHaveLength(1);
  await act(async () => {
    calls[0].deferred.resolve(upgradeMapping);
  });
  screen.getByText("crit recently");
  return view;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("one tap = one POST /diff (RULING-16/17, S2)", () => {
  it("first diff omits preset/overrides; a chip tap sends the full accumulated set", async () => {
    const { diff, calls } = fakeDiff();
    await renderVerdict(diff, calls);
    expect(calls[0].body).toEqual({ item_text: ITEM }); // §10: build default

    fireEvent.click(screen.getByText("crit recently"));
    expect(calls).toHaveLength(2);
    expect(calls[1].body).toEqual({
      item_text: ITEM,
      preset: "mapping", // §7: echo of the last response's preset
      overrides: [{ assumption_id: "config.elemental_overload", value: false }],
    });

    await act(async () => {
      calls[1].deferred.resolve(rediffedCard);
    });
    fireEvent.click(screen.getByText("flasks up"));
    expect(calls).toHaveLength(3);
    expect(calls[2].body.overrides).toEqual([
      { assumption_id: "config.elemental_overload", value: false },
      { assumption_id: "config.flasks_up", value: false },
    ]);
  });

  it("200 replaces the card: new diff_id deep link + ↺ on the overridden chip", async () => {
    const { diff, calls } = fakeDiff();
    const { container } = await renderVerdict(diff, calls);

    fireEvent.click(screen.getByText("crit recently"));
    await act(async () => {
      calls[1].deferred.resolve(rediffedCard);
    });

    expect(container.querySelector(".details-link")?.getAttribute("href")).toBe(
      `/breakdown/${encodeURIComponent("d-8f2c41a7#ovr-0123456789ab")}`,
    );
    const overridden = container.querySelector(".chip--overridden");
    expect(overridden?.textContent).toContain("↺");
    expect(overridden?.textContent).toContain("crit recently");
  });
});

describe("REDIFFING (§8.3, snapshot row 11)", () => {
  it("tapped chip spins, ALL chips go non-interactive, double-tap cannot fan out (S2)", async () => {
    const { diff, calls } = fakeDiff();
    const { container } = await renderVerdict(diff, calls);

    fireEvent.click(screen.getByText("crit recently"));

    // Inline spinner replaces the tapped chip's label; its name is preserved.
    expect(container.querySelector(".chip--pending .chip-spinner")).not.toBeNull();
    expect(container.querySelector(".chip--pending")?.getAttribute("aria-label")).toBe("crit recently");
    // Every chip non-interactive: buttons disabled, display-only span marked.
    expect(container.querySelectorAll("button.chip:not(:disabled)")).toHaveLength(0);
    expect(container.querySelector(".chip-strip")?.getAttribute("aria-busy")).toBe("true");

    // A second tap during flight issues NO second request (one server action
    // per explicit user action, and the strip is disabled: S2).
    fireEvent.click(screen.getByText("flasks up"));
    expect(calls).toHaveLength(2);

    expect(container.querySelector(".verdict-card")).toMatchSnapshot();

    // Resolution returns interactivity.
    await act(async () => {
      calls[1].deferred.resolve(rediffedCard);
    });
    expect(container.querySelector(".chip-spinner")).toBeNull();
    expect(container.querySelectorAll("button.chip:not(:disabled)")).toHaveLength(2);
  });
});

describe("revert-on-failure (§8.3, RULING-21)", () => {
  it("non-200 → mutation undone, card unchanged, transient message for 3 s in the sentence slot", async () => {
    const { diff, calls } = fakeDiff();
    const { container } = await renderVerdict(diff, calls);

    fireEvent.click(screen.getByText("crit recently"));
    await act(async () => {
      calls[1].deferred.reject(httpError(500));
    });

    // Reverted: no ↺, no spinner, original card, chips live again.
    expect(container.querySelector(".chip--overridden")).toBeNull();
    expect(container.querySelector(".chip-spinner")).toBeNull();
    expect(container.querySelectorAll("button.chip:not(:disabled)")).toHaveLength(2);
    // The sentence slot carries the exact transient text (I2 element count intact).
    expect(screen.getByText(RECOMPUTE_FAILED_MESSAGE)).toBeTruthy();
    expect(screen.queryByText(`"${upgradeMapping.sentence}"`)).toBeNull();

    // After 3 s the original sentence returns; the tap did NOT commit.
    act(() => {
      vi.advanceTimersByTime(TRANSIENT_MESSAGE_MS);
    });
    expect(screen.getByText(`"${upgradeMapping.sentence}"`)).toBeTruthy();

    // The failed tap left no trace: the next tap sends only its own override.
    fireEvent.click(screen.getByText("flasks up"));
    expect(calls[2].body.overrides).toEqual([{ assumption_id: "config.flasks_up", value: false }]);
  });

  it("timeout at 3000 ms cancels the request and reverts the same way (RULING-19)", async () => {
    const { diff, calls } = fakeDiff();
    const { container } = await renderVerdict(diff, calls);

    fireEvent.click(screen.getByText("crit recently"));
    act(() => {
      vi.advanceTimersByTime(DIFF_TIMEOUT_MS);
    });
    await act(async () => {}); // flush the cancel rejection

    expect(calls[1].deferred.cancelSpy).toHaveBeenCalledTimes(1);
    expect(container.querySelector(".chip--overridden")).toBeNull();
    expect(screen.getByText(RECOMPUTE_FAILED_MESSAGE)).toBeTruthy();
  });
});

describe("new item = new session (RULING-18)", () => {
  it("clears confirmed overrides and cancels any in-flight re-diff", async () => {
    const { diff, calls } = fakeDiff();
    const { container } = await renderVerdict(diff, calls);

    fireEvent.click(screen.getByText("crit recently"));
    await act(async () => {
      calls[1].deferred.resolve(rediffedCard);
    });
    expect(container.querySelector(".chip--overridden")).not.toBeNull();

    fireEvent.click(screen.getByText("new-item"));
    expect(calls).toHaveLength(3);
    expect(calls[2].body).toEqual({ item_text: OTHER_ITEM }); // fresh: no preset, no overrides

    await act(async () => {
      calls[2].deferred.resolve(upgradeMapping);
    });
    expect(container.querySelector(".chip--overridden")).toBeNull();
  });

  it("a hotkey press mid-rediff aborts the in-flight request; its late resolution is dropped", async () => {
    const { diff, calls } = fakeDiff();
    const { container } = await renderVerdict(diff, calls);

    fireEvent.click(screen.getByText("crit recently"));
    fireEvent.click(screen.getByText("new-item"));
    expect(calls[1].deferred.promise.isCancelled).toBe(true);

    await act(async () => {
      calls[2].deferred.resolve(upgradeMapping);
    });
    // The new session's card is clean; the cancelled tap left nothing behind.
    expect(container.querySelector(".chip--overridden")).toBeNull();
    expect(screen.queryByText(RECOMPUTE_FAILED_MESSAGE)).toBeNull();
  });
});

describe("LOADING + error panels (§8.1/8.2, snapshot row 10)", () => {
  it("renders nothing for the first 120 ms, then the exact LOADING line", () => {
    const { diff } = fakeDiff();
    const { container } = render(<Harness diff={diff} />);
    expect(container.querySelector("section")).toBeNull(); // flash guard [RULING-19]

    act(() => {
      vi.advanceTimersByTime(LOADING_FLASH_GUARD_MS);
    });
    expect(screen.getByText("Evaluating…")).toBeTruthy();
    expect(container.querySelector("section")).toMatchSnapshot();
  });

  it("404 → 'No build imported.' with the single import affordance", async () => {
    const { diff, calls } = fakeDiff();
    const { container } = render(<Harness diff={diff} />);
    await act(async () => {
      calls[0].deferred.reject(httpError(404));
    });
    expect(screen.getByText("No build imported.")).toBeTruthy();
    const link = screen.getByText("Import a build ▸");
    expect(link.tagName).toBe("A");
    expect(container.querySelector("section")).toMatchSnapshot();
  });

  it("422 → exact unparseable text, no affordance", async () => {
    const { diff, calls } = fakeDiff();
    const { container } = render(<Harness diff={diff} />);
    await act(async () => {
      calls[0].deferred.reject(httpError(422));
    });
    expect(screen.getByText("Couldn't read that item — copy it in game with Ctrl+C.")).toBeTruthy();
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(container.querySelector("section")).toMatchSnapshot();
  });

  it("network failure / 5xx / initial-diff timeout → 'Advisor engine isn't running.'", async () => {
    const { diff, calls } = fakeDiff();
    const { container } = render(<Harness diff={diff} />);
    await act(async () => {
      calls[0].deferred.reject(new Error("fetch failed"));
    });
    expect(screen.getByText("Advisor engine isn't running.")).toBeTruthy();
    expect(container.querySelector("section")).toMatchSnapshot();
  });

  it("initial diff timing out at 3000 ms lands in ERROR_UNAVAILABLE (§8.1)", async () => {
    const { diff, calls } = fakeDiff();
    render(<Harness diff={diff} />);
    act(() => {
      vi.advanceTimersByTime(DIFF_TIMEOUT_MS);
    });
    await act(async () => {});
    expect(calls[0].deferred.cancelSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Advisor engine isn't running.")).toBeTruthy();
  });
});
