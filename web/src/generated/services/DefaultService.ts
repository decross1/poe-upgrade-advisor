/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { Breakdown } from '../models/Breakdown';
import type { BuildSummary } from '../models/BuildSummary';
import type { VerdictCard } from '../models/VerdictCard';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class DefaultService {
    /**
     * Current active build summary
     * @returns BuildSummary OK
     * @throws ApiError
     */
    public static getActiveBuild(): CancelablePromise<BuildSummary> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/build',
            errors: {
                404: `No build imported`,
            },
        });
    }
    /**
     * Import a build (PoB code/XML or account+character)
     * @param requestBody
     * @returns BuildSummary Imported
     * @throws ApiError
     */
    public static importBuild(
        requestBody: {
            /**
             * PoB share code or raw XML
             */
            pob_code?: string;
            account?: string;
            character?: string;
        },
    ): CancelablePromise<BuildSummary> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/build',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Unparseable build`,
            },
        });
    }
    /**
     * The core call — clipboard item vs equipped, under inferred assumptions
     * @param requestBody
     * @returns VerdictCard Verdict
     * @throws ApiError
     */
    public static diffItem(
        requestBody: {
            /**
             * Raw Ctrl+C clipboard text (untrusted)
             */
            item_text: string;
            /**
             * Omit to use build default
             */
            preset?: 'mapping' | 'bossing' | 'balanced';
            /**
             * One-tap assumption flips (Doctrine I3)
             */
            overrides?: Array<{
                assumption_id: string;
                value: any;
            }>;
        },
    ): CancelablePromise<VerdictCard> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/diff',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                404: `No active build`,
                422: `Item text unparseable`,
            },
        });
    }
    /**
     * Rank pasted/stored items by score delta (Tier 3)
     * @param requestBody
     * @returns any Ranked results
     * @throws ApiError
     */
    public static scanStash(
        requestBody: {
            items: Array<string>;
            preset?: 'mapping' | 'bossing' | 'balanced';
        },
    ): CancelablePromise<{
        results: Array<{
            index: number;
            verdict: VerdictCard;
        }>;
    }> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/scan',
            body: requestBody,
            mediaType: 'application/json',
        });
    }
    /**
     * Tier-2/3 detail for a previous diff
     * @param diffId
     * @returns Breakdown Full mod-level delta tree + raw PoB breakdown reference
     * @throws ApiError
     */
    public static getBreakdown(
        diffId: string,
    ): CancelablePromise<Breakdown> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/breakdown/{diff_id}',
            path: {
                'diff_id': diffId,
            },
            errors: {
                404: `Expired or unknown diff_id`,
            },
        });
    }
}
