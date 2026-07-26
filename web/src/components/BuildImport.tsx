import { useState } from "react";
import type { FormEvent } from "react";
import type { BuildSummary } from "../generated/models/BuildSummary";

/**
 * TASK-207 (issue #29) — the web build-import surface. The spec's
 * ERROR_NO_BUILD state deep-links here and mvp_launch.md promises "Import
 * your build once": paste a PoB code/XML → one POST /build per submit →
 * success/failure states rendered.
 *
 * Portability contract (web/test/sourceHygiene.test.ts): this component does
 * NO network I/O. The POST lives in the generated client; the caller injects
 * it as `onImport` (see src/demo/importBuildClient.ts). One submit = one
 * request — Doctrine S2's one-action-per-keypress applied to the web tier.
 */

/** Outcome of one import attempt, already mapped off the wire by the caller. */
export type BuildImportResult =
  | { ok: true; summary: BuildSummary }
  /** Contract status on failure: 422 = unparseable build; 0 = no response. */
  | { ok: false; status: number };

export interface BuildImportProps {
  /** Called once per submit with the trimmed paste; resolves the attempt's outcome. */
  onImport: (pobCode: string) => Promise<BuildImportResult>;
}

type ImportState =
  | { phase: "editing" } // initial + after a failed attempt (textarea keeps its content)
  | { phase: "submitting" }
  | { phase: "success"; summary: BuildSummary }
  | { phase: "invalid" } // contract 422 — the paste could not be parsed
  | { phase: "unavailable" }; // anything else: no local server, unexpected status

export function BuildImport({ onImport }: BuildImportProps) {
  const [pobCode, setPobCode] = useState("");
  const [state, setState] = useState<ImportState>({ phase: "editing" });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const code = pobCode.trim();
    if (code === "" || state.phase === "submitting") return;
    setState({ phase: "submitting" });
    void onImport(code).then((result) => {
      if (result.ok) setState({ phase: "success", summary: result.summary });
      else if (result.status === 422) setState({ phase: "invalid" });
      else setState({ phase: "unavailable" });
    });
  };

  if (state.phase === "success") {
    const { summary } = state;
    return (
      <section className="build-import" aria-label="Import a build">
        <h2>Import a build</h2>
        <div className="build-import-success" role="status">
          <p className="build-import-success-word">Build imported</p>
          <dl className="build-summary">
            <div className="build-summary-row">
              <dt>Class</dt>
              <dd>
                {summary.character_class}
                {summary.ascendancy ? ` (${summary.ascendancy})` : ""}
              </dd>
            </div>
            <div className="build-summary-row">
              <dt>Level</dt>
              <dd>{summary.level}</dd>
            </div>
            <div className="build-summary-row">
              <dt>Main skill</dt>
              <dd>
                {summary.main_skill.name}
                {summary.main_skill.inferred ? " (inferred)" : ""}
              </dd>
            </div>
            <div className="build-summary-row">
              <dt>Default preset</dt>
              <dd>{summary.preset_default}</dd>
            </div>
          </dl>
        </div>
        <button
          type="button"
          className="build-import-reset"
          onClick={() => {
            setPobCode("");
            setState({ phase: "editing" });
          }}
        >
          Import a different build
        </button>
      </section>
    );
  }

  return (
    <section className="build-import" aria-label="Import a build">
      <h2>Import a build</h2>
      <form onSubmit={submit}>
        <label className="build-import-label" htmlFor="pob-code-input">
          Path of Building code or XML
        </label>
        <textarea
          id="pob-code-input"
          className="build-import-input"
          rows={5}
          value={pobCode}
          placeholder="Paste your PoB share code here"
          onChange={(e) => {
            setPobCode(e.target.value);
            // Editing after a failure clears the error back to neutral.
            if (state.phase === "invalid" || state.phase === "unavailable") {
              setState({ phase: "editing" });
            }
          }}
        />
        {state.phase === "invalid" && (
          <p className="build-import-error" role="alert">
            That build couldn't be parsed. Copy the full code from Path of Building (Import/Export →
            Share) and try again.
          </p>
        )}
        {state.phase === "unavailable" && (
          <p className="build-import-error" role="alert">
            Couldn't reach the local server. Start it and try again.
          </p>
        )}
        <button
          type="submit"
          className="build-import-submit"
          disabled={pobCode.trim() === "" || state.phase === "submitting"}
        >
          {state.phase === "submitting" ? "Importing…" : "Import build"}
        </button>
      </form>
    </section>
  );
}
