/**
 * MIERU intro timeline (all values in ms). The CSS keyframes in mieru-intro.css
 * are authored as percentages of TOTAL (4400ms); keep both in sync.
 */
export const TOTAL = 4400;
export const FAILSAFE = 5000;

export const EASE = {
  /** Structural morphs (cells -> bars -> mark) */
  inOut: "cubic-bezier(0.65, 0, 0.35, 1)",
  /** Reveals (mark, wordmark, tagline) */
  out: "cubic-bezier(0.16, 1, 0.3, 1)",
  /** Final overlay fade */
  fade: "cubic-bezier(0.4, 0, 0.2, 1)",
} as const;

export const PHASES = [
  {
    id: "data",
    label: "Data emerges",
    start: 0,
    end: 800,
    ease: EASE.out,
    detail: "6 cells fade in, staggered 70ms, 700ms each; dashed trend line wipes in 200–900ms.",
  },
  {
    id: "intel",
    label: "Data becomes intelligence",
    start: 800,
    end: 1800,
    ease: EASE.inOut,
    detail: "Cells morph into 4 bars 800–1700ms; baseline draws 900–1500ms; connected points 1300–1800ms.",
  },
  {
    id: "reveal",
    label: "Logo reveal",
    start: 1800,
    end: 2700,
    ease: EASE.out,
    detail: "Bars contract into the mark 1800–2300ms; mark scales 0.72→1 1850–2450ms; 見 fades in 2150–2550ms; wordmark opens 2350–3050ms.",
  },
  {
    id: "brand",
    label: "Brand moment",
    start: 2700,
    end: 3750,
    ease: EASE.out,
    detail: "Tagline rises 0.5em + fades 2800–3300ms, then a calm hold with a 1.2% settle.",
  },
  {
    id: "exit",
    label: "Crossfade to app",
    start: 3750,
    end: 4400,
    ease: EASE.fade,
    detail: "Overlay opacity 1→0 reveals the live app underneath; overlay unmounts on animationend.",
  },
] as const;
