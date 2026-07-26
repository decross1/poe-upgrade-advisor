/**
 * TASK-301 wiring: DetailsPanel's `loadBreakdown` backed by the GENERATED
 * client — the one sanctioned network boundary (web/test/sourceHygiene.test.ts).
 * One call = one GET /breakdown/{diff_id} per the contract.
 */
import { DefaultService } from "../generated/services/DefaultService";
import type { LoadBreakdown } from "../components/DetailsPanel";

export const loadBreakdownViaClient: LoadBreakdown = (diffId) =>
  DefaultService.getBreakdown(diffId);
