import { useSyncExternalStore } from "react";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "mieru-theme";
const SYSTEM_QUERY = "(prefers-color-scheme: dark)";
const listeners = new Set<() => void>();
const serverSnapshot = { preference: "system", resolved: "light", setPreference } as const;
let snapshot: { preference: ThemePreference; resolved: ResolvedTheme; setPreference: typeof setPreference } = serverSnapshot;
let initialized = false;
let media: MediaQueryList | undefined;

function parsePreference(value: string | null): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

function readPreference(): ThemePreference {
  try {
    return parsePreference(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return "system";
  }
}

function update(preference: ThemePreference) {
  const resolved = preference === "system" ? (media?.matches ? "dark" : "light") : preference;
  if (typeof document !== "undefined") {
    const root = document.documentElement;
    const changing = root.dataset.theme !== undefined && root.dataset.theme !== resolved;
    if (changing) root.classList.add("theme-switching");
    root.dataset.theme = resolved;
    root.style.colorScheme = resolved;
    if (changing) {
      void root.offsetHeight;
      window.setTimeout(() => root.classList.remove("theme-switching"), 0);
    }
  }
  if (snapshot.preference === preference && snapshot.resolved === resolved) return;
  snapshot = { preference, resolved, setPreference };
  listeners.forEach((listener) => listener());
}

// Also called before React mounts, so chart effects always read the right CSS tokens.
export function initializeTheme() {
  if (initialized || typeof window === "undefined") return;
  initialized = true;
  try {
    media = window.matchMedia(SYSTEM_QUERY);
  } catch {
    // Older or restricted environments use light when the OS preference is unavailable.
  }
  update(readPreference());
}

function setPreference(preference: ThemePreference) {
  initializeTheme();
  try {
    window.localStorage.setItem(STORAGE_KEY, preference);
  } catch {
    // The current session still works when storage is disabled or full.
  }
  update(preference);
}

function onSystemChange() {
  update(snapshot.preference);
}

function onStorage(event: StorageEvent) {
  if (event.key === STORAGE_KEY || event.key === null) update(readPreference());
}

function subscribe(listener: () => void) {
  initializeTheme();
  if (listeners.size === 0) {
    if (media?.addEventListener) media.addEventListener("change", onSystemChange);
    else media?.addListener?.(onSystemChange);
    window.addEventListener("storage", onStorage);
    // Account for OS changes while there were no mounted consumers.
    onSystemChange();
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      if (media?.removeEventListener) media.removeEventListener("change", onSystemChange);
      else media?.removeListener?.(onSystemChange);
      window.removeEventListener("storage", onStorage);
    }
  };
}

export function useTheme() {
  initializeTheme();
  return useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => serverSnapshot,
  );
}
