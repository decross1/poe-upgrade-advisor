/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { Assumption } from './Assumption';
export type VerdictCard = {
    diff_id: string;
    verdict: VerdictCard.verdict;
    offense_delta_pct: number;
    defense_delta_pct: number;
    /**
     * Doctrine I2 cap
     */
    sentence: string;
    assumptions: Array<Assumption>;
    confidence: number;
    cant_evaluate_reasons?: Array<string>;
    preset: VerdictCard.preset;
    /**
     * Engine time; I6 telemetry
     */
    compute_ms?: number;
};
export namespace VerdictCard {
    export enum verdict {
        UPGRADE = 'UPGRADE',
        SIDEGRADE = 'SIDEGRADE',
        DOWNGRADE = 'DOWNGRADE',
        CANT_EVALUATE = 'CANT_EVALUATE',
    }
    export enum preset {
        MAPPING = 'mapping',
        BOSSING = 'bossing',
        BALANCED = 'balanced',
    }
}

