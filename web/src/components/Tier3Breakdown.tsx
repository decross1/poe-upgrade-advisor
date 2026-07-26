/**
 * TASK-301 (issue #13) — Tier-3 view: the raw engine breakdown tree
 * (contract Breakdown.pob_breakdown, schema owned by engine/). Rendered
 * verbatim — Tier 3 is where full depth lives (Doctrine I7); the surface
 * adds nothing and hides nothing. Absent tree is a first-class state.
 */
export function Tier3Breakdown({ tree }: { tree?: Record<string, unknown> }) {
  return (
    <section className="tier3-breakdown" aria-label="Raw engine breakdown">
      <h3>Raw breakdown (Tier 3)</h3>
      {tree ? (
        <pre className="payload-preview">{JSON.stringify(tree, null, 2)}</pre>
      ) : (
        <p className="breakdown-empty">No raw breakdown captured for this diff.</p>
      )}
    </section>
  );
}
