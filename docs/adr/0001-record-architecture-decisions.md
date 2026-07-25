# ADR-0001: Record architecture decisions

- Status: accepted
- Date: 2026-07-25
- Deciders: bootstrap

## Context
An amnesiac agent org needs durable, searchable rulings; email history is not memory.

## Decision
All binding decisions (arbitrations, contract changes, doctrine interpretations) are recorded as ADRs in `docs/adr/`, numbered sequentially, using TEMPLATE.md. PRs implementing a ruling must reference its ADR.

## Consequences
Agents reconstruct context from ADRs; the meta loop (L5) audits ADRs weekly for contradictions.
