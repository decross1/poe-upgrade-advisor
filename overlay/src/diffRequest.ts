/**
 * THE contract-conformance point of the shell (frontend charter: consume
 * contracts/openapi.yaml via the generated client; never hand-roll types or
 * invent fields). This is the ONLY /diff call site in the overlay — main.ts
 * and the headless tests both bind through here.
 *
 * The generated client lives in web/src/generated (single generation, shared
 * by web and overlay); importing it across the package boundary is
 * deliberate — duplicating or re-generating it here would fork the contract.
 */
import { OpenAPI } from "../../web/src/generated/core/OpenAPI";
import { DefaultService } from "../../web/src/generated/services/DefaultService";
import type { CancelablePromise } from "../../web/src/generated/core/CancelablePromise";
import type { VerdictCard } from "../../web/src/lib/verdictFormat";

export type PostDiff = (itemText: string) => CancelablePromise<VerdictCard>;

/**
 * Point the generated client at baseUrl and return the /diff call the shell
 * uses. `preset` is omitted on purpose: the overlay always diffs under the
 * build default (docs/specs/verdict_card.md §10; overrides arrive with
 * TASK-204).
 */
export function bindGeneratedDiff(baseUrl: string): PostDiff {
  OpenAPI.BASE = baseUrl;
  return (itemText) => {
    const request = DefaultService.diffItem({ item_text: itemText });
    // The repo carries two generated encodings of the SAME contract schema:
    // the service client (string enums) and api-types (literal unions, which
    // the shared card component consumes). Reconcile them here — the single
    // client boundary — so everything downstream speaks the component's type.
    const adapted = request.then((card) => card as VerdictCard) as CancelablePromise<VerdictCard>;
    adapted.cancel = () => request.cancel();
    return adapted;
  };
}
