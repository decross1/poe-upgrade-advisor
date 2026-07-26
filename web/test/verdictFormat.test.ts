import { describe, expect, it } from "vitest";
import {
  barFillFraction,
  barOverflows,
  deltaTone,
  formatDelta,
  MINUS_SIGN,
  showLowConfidenceBadge,
  verdictDisplayText,
} from "../src/lib/verdictFormat";
import type { VerdictCard } from "../src/lib/verdictFormat";

describe("formatDelta (spec §5: explicit sign, one decimal, % suffix)", () => {
  it("formats positive, negative, and zero deltas", () => {
    expect(formatDelta(12.4)).toBe("+12.4%");
    expect(formatDelta(-1.8)).toBe(`${MINUS_SIGN}1.8%`);
    expect(formatDelta(0)).toBe("0.0%");
  });

  it("RULING-9: |delta| < 0.05 renders unsigned 0.0%", () => {
    expect(formatDelta(0.049)).toBe("0.0%");
    expect(formatDelta(-0.049)).toBe("0.0%");
    expect(formatDelta(0.05)).toBe("+0.1%"); // rounds at the boundary, stays signed
    expect(formatDelta(-0.06)).toBe(`${MINUS_SIGN}0.1%`);
  });

  it("the number is always exact, even past bar full-scale", () => {
    expect(formatDelta(312)).toBe("+312.0%");
  });
});

describe("bar geometry (RULING-10: full scale = 25pp)", () => {
  it("fill fraction is clamp(|delta| / 25, 0, 1)", () => {
    expect(barFillFraction(0)).toBe(0);
    expect(barFillFraction(12.5)).toBe(0.5);
    expect(barFillFraction(-25)).toBe(1);
    expect(barFillFraction(50)).toBe(1);
  });

  it("overflow chevron only when |delta| > 25", () => {
    expect(barOverflows(25)).toBe(false);
    expect(barOverflows(-25)).toBe(false);
    expect(barOverflows(25.1)).toBe(true);
    expect(barOverflows(-312)).toBe(true);
  });
});

describe("deltaTone (RULING-5: positive is better, per-bar)", () => {
  it("positive/negative/neutral independently per bar", () => {
    expect(deltaTone(3.1)).toBe("positive");
    expect(deltaTone(-0.4)).toBe("negative");
    expect(deltaTone(0.01)).toBe("neutral");
  });
});

describe("verdictDisplayText (I2 exact wording)", () => {
  it("CANT_EVALUATE wire value renders with the apostrophe", () => {
    expect(verdictDisplayText("CANT_EVALUATE")).toBe("CAN'T EVALUATE");
    expect(verdictDisplayText("UPGRADE")).toBe("UPGRADE");
    expect(verdictDisplayText("SIDEGRADE")).toBe("SIDEGRADE");
    expect(verdictDisplayText("DOWNGRADE")).toBe("DOWNGRADE");
  });
});

describe("showLowConfidenceBadge (RULING-8: mirrored 0.75 constant)", () => {
  const base = { verdict: "UPGRADE", confidence: 0.8 } as VerdictCard;
  it("shows below 0.75 for scored verdicts, never for CANT_EVALUATE", () => {
    expect(showLowConfidenceBadge({ ...base, confidence: 0.74 })).toBe(true);
    expect(showLowConfidenceBadge({ ...base, confidence: 0.75 })).toBe(false);
    expect(showLowConfidenceBadge({ ...base, confidence: 0.9 })).toBe(false);
    expect(showLowConfidenceBadge({ ...base, verdict: "CANT_EVALUATE", confidence: 0.5 })).toBe(false);
  });
});
