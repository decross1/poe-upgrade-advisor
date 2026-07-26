/**
 * TASK-207 wiring: BuildImport's `onImport` backed by the GENERATED client —
 * the one sanctioned network boundary (web/test/sourceHygiene.test.ts). One
 * call here = one POST /build per the contract; ApiError statuses map to the
 * component's result union (422 → invalid code; anything else → unavailable).
 */
import { ApiError } from "../generated/core/ApiError";
import { DefaultService } from "../generated/services/DefaultService";
import type { BuildImportResult } from "../components/BuildImport";

export async function importBuildViaClient(pobCode: string): Promise<BuildImportResult> {
  try {
    const summary = await DefaultService.importBuild({ pob_code: pobCode });
    return { ok: true, summary };
  } catch (err) {
    return { ok: false, status: err instanceof ApiError ? err.status : 0 };
  }
}
