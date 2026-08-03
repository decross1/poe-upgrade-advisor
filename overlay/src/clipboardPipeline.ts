/**
 * Headless-testable composition of clipboard detection, generated-client
 * /diff flow, and renderer state delivery. main.ts supplies Electron adapters;
 * tests supply a mocked clipboard source and golden VerdictCard responses.
 */
import type { Assumption } from "../../web/src/lib/overrides";
import {
  createClipboardWatcher,
  type ClipboardSource,
  type ClipboardWatcher,
} from "./clipboardWatcher";
import { createDiffFlow, type DiffFlowDeps } from "./diffFlow";

export interface ClipboardPipelineDeps extends DiffFlowDeps {
  clipboard: ClipboardSource;
  pollMs?: number;
}

export interface ClipboardPipeline extends ClipboardWatcher {
  onChipTap: (assumption: Assumption) => Promise<void>;
}

export function createClipboardPipeline(deps: ClipboardPipelineDeps): ClipboardPipeline {
  const flow = createDiffFlow({
    postDiff: deps.postDiff,
    onState: deps.onState,
    timeoutMs: deps.timeoutMs,
    transientMs: deps.transientMs,
  });
  const watcher = createClipboardWatcher({
    clipboard: deps.clipboard,
    pollMs: deps.pollMs,
    onItemText: flow.onItemText,
  });

  return { ...watcher, onChipTap: flow.onChipTap };
}
