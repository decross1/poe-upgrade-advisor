/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type Breakdown = {
    diff_id: string;
    /**
     * Tier-2 — mods ranked by contribution to the delta
     */
    drivers: Array<{
        mod_text: string;
        contribution_pct: number;
        /**
         * e.g. total_dps
         */
        stat: string;
    }>;
    /**
     * Tier-3 — raw engine breakdown tree (schema owned by engine/)
     */
    pob_breakdown?: Record<string, any>;
};

