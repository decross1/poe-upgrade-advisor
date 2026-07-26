/**
 * ShellApp — the renderer's root component, exported for headless tests.
 * Subscribes to the preload bridge for shell states and routes every anchor
 * click through the bridge to the system browser (Tier-2/3 lives in the web
 * app, I7; the overlay never grows its own details view).
 */
import { useEffect, useState } from "react";
import type { PoeOverlayBridge } from "../preload";
import type { ShellState } from "../shellState";
import { OverlayCard } from "./OverlayCard";

declare global {
  interface Window {
    poeOverlay?: PoeOverlayBridge;
  }
}

export function ShellApp() {
  const [state, setState] = useState<ShellState>({ kind: "HIDDEN" });

  useEffect(() => {
    window.poeOverlay?.onState(setState);
  }, []);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const anchor = (event.target as Element | null)?.closest?.("a[href]");
      const href = anchor?.getAttribute("href");
      if (href && href.startsWith("/")) {
        event.preventDefault();
        window.poeOverlay?.openDetails(href);
      }
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);

  return (
    <OverlayCard
      state={state}
      onChipTap={(assumption) => window.poeOverlay?.tapChip(assumption)}
    />
  );
}
