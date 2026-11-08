import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { MieruMark } from "./MieruLogo";
import { FAILSAFE } from "./timeline";
import "./mieru-intro.css";

type Vars = CSSProperties & Record<`--${string}`, string>;

export const INTRO_STORAGE_KEY = "mieru:intro-seen";

/** Cell (x0,y0) -> bar (x1,y1,h1) -> mini bar inside the mark (x2,y2,h2). Units: em. */
const BARS: Vars[] = [
  {
    "--x0": "1.6em",
    "--y0": "5em",
    "--x1": "2em",
    "--y1": "5.4em",
    "--h1": "2.6em",
    "--x2": "5.71em",
    "--y2": "4.9em",
    "--h2": "0.7em",
    "--c1": "#21528f",
    "--d": "0ms",
    "--ox": "-0.5em",
    "--oy": "0.3em",
  },
  {
    "--x0": "1.6em",
    "--y0": "2.6em",
    "--x1": "4.8em",
    "--y1": "4.2em",
    "--h1": "3.8em",
    "--x2": "6.43em",
    "--y2": "4.6em",
    "--h2": "1em",
    "--c1": "#2763ad",
    "--d": "70ms",
    "--ox": "-0.3em",
    "--oy": "-0.4em",
  },
  {
    "--x0": "5.8em",
    "--y0": "5em",
    "--x1": "7.6em",
    "--y1": "3em",
    "--h1": "5em",
    "--x2": "7.15em",
    "--y2": "4.25em",
    "--h2": "1.35em",
    "--c1": "#2a78d6",
    "--d": "210ms",
    "--ox": "0.2em",
    "--oy": "0.5em",
  },
  {
    "--x0": "10em",
    "--y0": "2.6em",
    "--x1": "10.4em",
    "--y1": "1.6em",
    "--h1": "6.4em",
    "--x2": "7.87em",
    "--y2": "3.85em",
    "--h2": "1.75em",
    "--c0": "rgba(42,120,214,0.6)",
    "--c1": "#4a97ee",
    "--g": "0 0 1.4em rgba(42,120,214,0.45)",
    "--d": "280ms",
    "--ox": "0.5em",
    "--oy": "-0.3em",
  },
];
const GHOSTS: Vars[] = [
  { "--x0": "5.8em", "--y0": "2.6em", "--x1": "7.6em", "--y1": "3em", "--d": "140ms", "--ox": "0.3em", "--oy": "-0.5em" },
  { "--x0": "10em", "--y0": "5em", "--x1": "10.4em", "--y1": "4em", "--d": "350ms", "--ox": "0.6em", "--oy": "0.3em" },
];
const POINTS: [number, number][] = [
  [2.8, 4.9],
  [5.6, 3.7],
  [8.4, 2.5],
  [11.2, 1.1],
];

export interface MieruIntroProps {
  /** Called once the overlay has fully faded (or was skipped). Unmount the intro here. */
  onFinish: () => void;
  /** Position inside the nearest positioned ancestor instead of the viewport (previews). */
  contained?: boolean;
  tagline?: string;
}

export function MieruIntro({ onFinish, contained = false, tagline = "See beyond the spreadsheet." }: MieruIntroProps) {
  const [skipping, setSkipping] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const done = useRef(false);
  const skipStarted = useRef(false);
  const finish = useCallback(() => {
    if (done.current) return;
    done.current = true;
    onFinish();
  }, [onFinish]);

  const skip = useCallback(() => {
    if (skipStarted.current) return;
    skipStarted.current = true;
    const overlay = rootRef.current;
    if (overlay) overlay.style.setProperty("--mi-skip-from", getComputedStyle(overlay).opacity);
    setSkipping(true);
  }, []);

  useLayoutEffect(() => {
    const overlay = rootRef.current;
    if (skipping || !overlay?.parentElement) return;
    const covered = Array.from(overlay.parentElement.children).filter((element) => element !== overlay && !element.hasAttribute("inert"));
    covered.forEach((element) => element.setAttribute("inert", ""));
    return () => covered.forEach((element) => element.removeAttribute("inert"));
  }, [skipping]);

  useEffect(() => {
    const failsafe = window.setTimeout(finish, FAILSAFE);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") skip();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(failsafe);
      window.removeEventListener("keydown", onKey);
    };
  }, [finish, skip]);

  return (
    <div
      ref={rootRef}
      className={`mi-intro${contained ? " mi-intro--contained" : ""}${skipping ? " is-skipping" : ""}`}
      role="presentation"
      onClick={skip}
      onAnimationEnd={(event) => {
        if (event.target === event.currentTarget && /^mi-(exit|skip|reduced)$/.test(event.animationName)) finish();
      }}
    >
      <div className="mi-scene" aria-hidden="true">
        <div className="mi-stage">
          <svg className="mi-svg" viewBox="0 0 14 9">
            <path
              className="mi-trend"
              d="M1.8 7 L4.4 5.7 L6.3 6.1 L8.9 4.1 L12.6 2.3"
              fill="none"
              stroke="#2A78D6"
              strokeWidth="0.11"
              strokeDasharray="0.34 0.26"
              strokeLinecap="round"
            />
            <polyline
              className="mi-link"
              pathLength={1}
              points={POINTS.map((point) => point.join(" ")).join(" ")}
              fill="none"
              stroke="rgba(160,200,245,0.75)"
              strokeWidth="0.06"
              strokeLinejoin="round"
            />
            {POINTS.map(([x, y], index) => (
              <circle key={index} className="mi-dot" cx={x} cy={y} r="0.15" fill="#fff" style={{ animationDelay: `${index * 40}ms` }} />
            ))}
          </svg>
          <div className="mi-baseline" />
          {GHOSTS.map((style, index) => (
            <div key={`g${index}`} className="mi-cell-wrap" style={style}>
              <div className="mi-ghost" />
            </div>
          ))}
          {BARS.map((style, index) => (
            <div key={index} className="mi-cell-wrap" style={style}>
              <div className="mi-bar" />
            </div>
          ))}
        </div>

        <div className="mi-brand">
          <div className="mi-lockup">
            <span className="mi-mark">
              <MieruMark size="100%" />
            </span>
            <span className="mi-word">
              <span className="mi-word-inner">
                <span className="mi-word-text">MIERU</span>
              </span>
            </span>
          </div>
        </div>
        <p className="mi-tagline">{tagline}</p>
      </div>

      <button
        type="button"
        className="mi-skip"
        onClick={(event) => {
          event.stopPropagation();
          skip();
        }}
      >
        Skip intro
      </button>
    </div>
  );
}

/** Plays once per browser session (or forever with storage="local"). Returns [show, dismiss]. */
export function useFirstVisitIntro(key = INTRO_STORAGE_KEY, storage: "session" | "local" = "session") {
  const [show, setShow] = useState(() => {
    try {
      return !(storage === "local" ? localStorage : sessionStorage).getItem(key);
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try {
      (storage === "local" ? localStorage : sessionStorage).setItem(key, "1");
    } catch {
      // Without storage the intro simply plays again on the next load.
    }
  }, [key, storage]);
  return [show, useCallback(() => setShow(false), [])] as const;
}

/**
 * Production splash, rendered as a sibling of the app root so route changes never replay it. While it shows, the
 * app underneath is inert; it releases the pre-paint navy background set by theme-init.js before its first paint
 * and unmounts itself when done.
 */
export function MieruSplash({ storageKey, tagline }: { storageKey?: string; tagline?: string }) {
  const [show, dismiss] = useFirstVisitIntro(storageKey);
  useLayoutEffect(() => {
    document.documentElement.removeAttribute("data-intro");
  }, []);
  return show ? <MieruIntro onFinish={dismiss} tagline={tagline} /> : null;
}
