import {
  NO_BUILD_MESSAGE,
  UNAVAILABLE_MESSAGE,
  UNPARSEABLE_MESSAGE,
  type SessionError,
} from "../lib/session";

export type CardStatusKind = "loading" | SessionError;

export interface CardStatusProps {
  kind: CardStatusKind;
  /** Deep link to web-app build import (ERROR_NO_BUILD's one affordance). */
  importHref?: string;
}

/**
 * LOADING / ERROR panels (spec §8.1/8.2): overlay UI states, NOT VerdictCards.
 * One short line + at most one affordance each, in the same card frame, and
 * never any settings/config UI (I1). Card text is exact per the §8.2 table;
 * errors carry no body schema, so nothing here renders server text (RULING-20).
 */
export function CardStatus({ kind, importHref }: CardStatusProps) {
  return (
    <section className={`verdict-card card-status card-status--${kind}`} aria-label="Advisor status">
      {kind === "loading" && <p className="card-status-line">Evaluating…</p>}
      {kind === "no_build" && (
        <>
          <p className="card-status-line">{NO_BUILD_MESSAGE}</p>
          <footer className="details-row">
            <a className="details-link" href={importHref ?? "/build/import"}>
              Import a build ▸
            </a>
          </footer>
        </>
      )}
      {kind === "unparseable" && <p className="card-status-line">{UNPARSEABLE_MESSAGE}</p>}
      {kind === "unavailable" && <p className="card-status-line">{UNAVAILABLE_MESSAGE}</p>}
    </section>
  );
}
