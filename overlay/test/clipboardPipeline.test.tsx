// @vitest-environment jsdom
/**
 * Stage-1 acceptance: mocked clipboard → header detection → one /diff →
 * bridge-delivered shared VerdictCard, exercised headlessly with the golden
 * contract fixtures. The lower-level diffFlow suite separately proves the
 * same PostDiff boundary uses the generated client over real HTTP.
 */
import { render } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VerdictCard } from "../../web/src/lib/verdictFormat";
import { createClipboardPipeline, type ClipboardPipeline } from "../src/clipboardPipeline";
import type { PostDiff } from "../src/diffRequest";
import { ShellApp } from "../src/renderer/ShellApp";
import type { ShellState } from "../src/shellState";

import cantEvaluateJson from "../../contracts/fixtures/cant_evaluate_trigger_build.json";
import downgradeJson from "../../contracts/fixtures/downgrade_mapping.json";
import sidegradeJson from "../../contracts/fixtures/sidegrade_bossing.json";
import upgradeJson from "../../contracts/fixtures/upgrade_mapping.json";

const ITEM_TEXT =
  "Item Class: Wands\r\nRarity: Rare\r\nDoom Branch\r\nProphecy Wand\r\n--------\r\n";

const CASES = [
  ["UPGRADE", upgradeJson],
  ["SIDEGRADE", sidegradeJson],
  ["DOWNGRADE", downgradeJson],
  ["CAN'T EVALUATE", cantEvaluateJson],
] as const;

const pipelines: ClipboardPipeline[] = [];
afterEach(() => {
  for (const pipeline of pipelines.splice(0)) pipeline.stop();
  delete window.poeOverlay;
});

function resolvedCard(card: VerdictCard): ReturnType<PostDiff> {
  const response = Promise.resolve(card) as unknown as ReturnType<PostDiff>;
  response.cancel = vi.fn();
  return response;
}

describe.each(CASES)("clipboard pipeline — %s golden card", (_verdict, cardJson) => {
  it("detects → requests exactly once → renders the card", async () => {
    const card = cardJson as VerdictCard;
    const clipboard = { text: "initial non-item", readText: () => clipboard.text };
    let deliverState: ((state: ShellState) => void) | undefined;
    window.poeOverlay = {
      onState: (callback) => {
        deliverState = callback;
      },
      openDetails: vi.fn(),
      tapChip: vi.fn(),
    };
    const { container } = render(<ShellApp />);

    const postDiff = vi.fn((_body) => resolvedCard(card)) as unknown as PostDiff;
    const pipeline = createClipboardPipeline({
      clipboard,
      postDiff,
      onState: (state) => deliverState?.(state),
      pollMs: 60_000,
    });
    pipelines.push(pipeline);
    pipeline.start();

    clipboard.text = ITEM_TEXT;
    await act(async () => {
      await pipeline.pollNow();
    });
    // Re-sampling unchanged clipboard contents cannot fan out requests.
    await pipeline.pollNow();

    expect(postDiff).toHaveBeenCalledTimes(1);
    expect(postDiff).toHaveBeenCalledWith({ item_text: ITEM_TEXT });
    expect(container.firstChild).toMatchSnapshot();
  });
});

it("non-item clipboard changes are ignored silently: no request and no card state", async () => {
  const clipboard = { text: "", readText: () => clipboard.text };
  const postDiff = vi.fn() as unknown as PostDiff;
  const states: ShellState[] = [];
  const pipeline = createClipboardPipeline({
    clipboard,
    postDiff,
    onState: (state) => states.push(state),
    pollMs: 60_000,
  });
  pipelines.push(pipeline);
  pipeline.start();

  for (const text of [
    "discord message",
    "Rarity: Rare\nMissing item class",
    "Item Class: Wands\nMissing rarity",
  ]) {
    clipboard.text = text;
    await pipeline.pollNow();
  }

  expect(postDiff).not.toHaveBeenCalled();
  expect(states).toEqual([]);
});
