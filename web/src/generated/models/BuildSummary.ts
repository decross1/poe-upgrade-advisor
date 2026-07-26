/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type BuildSummary = {
    build_id: string;
    character_class: string;
    ascendancy?: string;
    level: number;
    main_skill: {
        name: string;
        /**
         * false if user overrode
         */
        inferred: boolean;
        confidence?: number;
    };
    preset_default: BuildSummary.preset_default;
};
export namespace BuildSummary {
    export enum preset_default {
        MAPPING = 'mapping',
        BOSSING = 'bossing',
        BALANCED = 'balanced',
    }
}

