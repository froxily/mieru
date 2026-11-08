import source from "../../public/theme-init.js?raw";
import html from "../../index.html?raw";
import { createElement, StrictMode } from "react";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const plotly = vi.hoisted(() => ({ react: vi.fn().mockResolvedValue(undefined), purge: vi.fn(), Plots: { resize: vi.fn() } }));
vi.mock("plotly.js-cartesian-dist-min", () => ({ default: plotly }));
vi.mock("../features/datasets/useDatasets", () => ({ useActiveDatasets: () => [] }));
vi.mock("../features/olist/queries", () => ({ useOlistOverview: () => ({ data: undefined }) }));

let matches = false;
let callbacks: Set<() => void>;
let media: { readonly matches: boolean; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> };

beforeEach(() => {
  vi.resetModules();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("style");
  matches = false;
  callbacks = new Set();
  media = {
    get matches() {
      return matches;
    },
    addEventListener: vi.fn((_type: string, callback: () => void) => callbacks.add(callback)),
    removeEventListener: vi.fn((_type: string, callback: () => void) => callbacks.delete(callback)),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => media),
  );
  plotly.react.mockClear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("style");
});

function changeSystem(dark: boolean) {
  act(() => {
    matches = dark;
    callbacks.forEach((callback) => callback());
  });
}

describe("useTheme", () => {
  it("defaults to system, resolves light, and applies both HTML properties", async () => {
    const { useTheme } = await import("./theme");
    const { result, rerender } = renderHook(useTheme);
    expect(result.current).toMatchObject({ preference: "system", resolved: "light" });
    expect(window.matchMedia).toHaveBeenCalledWith("(prefers-color-scheme: dark)");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    const initial = result.current;
    rerender();
    expect(result.current).toBe(initial);
  });

  it.each(["light", "dark"] as const)("restores persisted %s over the OS preference", async (preference) => {
    matches = preference === "light";
    window.localStorage.setItem("mieru-theme", preference);
    const { useTheme } = await import("./theme");
    const { result } = renderHook(useTheme);
    expect(result.current).toMatchObject({ preference, resolved: preference });
  });

  it.each(["system", "invalid"])("resolves stored %s using the OS", async (stored) => {
    window.localStorage.setItem("mieru-theme", stored);
    matches = true;
    const { useTheme } = await import("./theme");
    const { result } = renderHook(useTheme);
    expect(result.current).toMatchObject({ preference: "system", resolved: "dark" });
    changeSystem(false);
    expect(result.current.resolved).toBe("light");
  });

  it("persists changes, ignores OS changes in explicit modes, and resumes system tracking", async () => {
    const { useTheme } = await import("./theme");
    const { result } = renderHook(useTheme);
    act(() => result.current.setPreference("dark"));
    expect(window.localStorage.getItem("mieru-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    changeSystem(false);
    expect(result.current.resolved).toBe("dark");
    act(() => result.current.setPreference("system"));
    expect(window.localStorage.getItem("mieru-theme")).toBe("system");
    expect(result.current.resolved).toBe("light");
    changeSystem(true);
    expect(result.current.resolved).toBe("dark");
  });

  it("shares one listener across consumers, cleans up, and handles StrictMode remounts", async () => {
    const { useTheme } = await import("./theme");
    const first = renderHook(useTheme, { wrapper: ({ children }) => createElement(StrictMode, null, children) });
    const second = renderHook(useTheme);
    expect(callbacks.size).toBe(1);
    act(() => first.result.current.setPreference("dark"));
    expect(second.result.current.resolved).toBe("dark");
    first.unmount();
    expect(callbacks.size).toBe(1);
    second.unmount();
    expect(callbacks.size).toBe(0);
  });

  it("tolerates blocked storage getters and still switches for the session", async () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new Error("Blocked");
    });
    matches = true;
    const { useTheme } = await import("./theme");
    const { result } = renderHook(useTheme);
    expect(result.current).toMatchObject({ preference: "system", resolved: "dark" });
    act(() => result.current.setPreference("light"));
    expect(result.current.resolved).toBe("light");
  });

  it("tolerates storage method failures", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("Denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Quota");
    });
    const { useTheme } = await import("./theme");
    const { result } = renderHook(useTheme);
    act(() => result.current.setPreference("dark"));
    expect(result.current.resolved).toBe("dark");
  });

  it("falls back safely when matchMedia is unavailable", async () => {
    vi.stubGlobal("matchMedia", undefined);
    const { useTheme } = await import("./theme");
    const { result } = renderHook(useTheme);
    expect(result.current.resolved).toBe("light");
    act(() => result.current.setPreference("dark"));
    expect(result.current.resolved).toBe("dark");
  });

  it("synchronizes preferences changed in another tab, including storage clearing", async () => {
    const { useTheme } = await import("./theme");
    const { result } = renderHook(useTheme);
    act(() => {
      window.localStorage.setItem("mieru-theme", "dark");
      window.dispatchEvent(new StorageEvent("storage", { key: "mieru-theme" }));
    });
    expect(result.current.resolved).toBe("dark");
    act(() => {
      window.localStorage.clear();
      window.dispatchEvent(new StorageEvent("storage", { key: null }));
    });
    expect(result.current).toMatchObject({ preference: "system", resolved: "light" });
  });

  it("updates Plotly when only the resolved theme changes, preserving the inner root", async () => {
    const { useTheme } = await import("./theme");
    const { Plot } = await import("../charts/Plot");
    const { result } = renderHook(useTheme);
    const data = [{ type: "bar", marker: { color: "#184f95" }, x: [1], y: [2] }];
    const { container } = render(createElement(Plot, { data, layout: { annotations: [{ font: { color: "#0e1525" } }] }, ariaLabel: "Test chart" }));
    await waitFor(() => expect(plotly.react).toHaveBeenCalledTimes(1));
    const plotRoot = plotly.react.mock.calls[0]?.[0] as HTMLElement;
    expect(plotRoot.parentElement).toHaveClass("chart-canvas");
    expect(plotRoot.className).toBe("");
    document.documentElement.style.setProperty("--chart-hover-text", "#e6ebf5");
    document.documentElement.style.setProperty("--chart-hover-bg", "#1b2940");
    changeSystem(true);
    await waitFor(() => expect(plotly.react).toHaveBeenCalledTimes(2));
    expect(result.current.resolved).toBe("dark");
    expect(plotly.react.mock.calls[1]?.[0]).toBe(plotRoot);
    expect(plotly.react.mock.calls[1]?.[1]).toMatchObject([{ marker: { color: "#78b4fa" } }]);
    expect(plotly.react.mock.calls[1]?.[2]).toMatchObject({
      annotations: [{ font: { color: "#e6ebf5" } }],
      hoverlabel: { bgcolor: "#1b2940", font: { color: "#e6ebf5" } },
    });
    expect(data[0]?.marker.color).toBe("#184f95");
    expect(container.querySelector(".chart-canvas")).toHaveClass("ready");
  });

  it("cycles System, Light, Dark using the keyboard with descriptive labels and tooltips", async () => {
    const { AppShell } = await import("../components/AppShell");
    const { MemoryRouter } = await import("react-router-dom");
    const user = userEvent.setup();
    render(createElement(MemoryRouter, null, createElement(AppShell, { children: "Dashboard" })));
    const button = screen.getByRole("button", { name: "Theme: system (light). Switch to light theme." });
    button.focus();
    expect(button).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(button).toHaveAccessibleName("Theme: light. Switch to dark theme.");
    await user.keyboard(" ");
    expect(button).toHaveAccessibleName("Theme: dark. Switch to system theme.");
    expect(button).toHaveAttribute("title", "Theme: dark. Switch to system theme.");
    expect(document.documentElement.dataset.theme).toBe("dark");
    await user.keyboard("{Enter}");
    expect(button).toHaveAccessibleName("Theme: system (light). Switch to light theme.");
    expect(button).toHaveFocus();
    expect(window.localStorage.getItem("mieru-theme")).toBe("system");
  });
});

describe("CSP-safe startup", () => {
  const runStartup = (window: unknown) => new Function("window", "document", source)(window, document);
  it.each([
    [null, true, "dark"],
    ["invalid", false, "light"],
    ["system", true, "dark"],
    ["light", true, "light"],
    ["dark", false, "dark"],
  ])("applies %s before the app mounts", (stored, dark, expected) => {
    runStartup({ localStorage: { getItem: () => stored }, matchMedia: () => ({ matches: dark }) });
    expect(document.documentElement.dataset.theme).toBe(expected);
    expect(document.documentElement.style.colorScheme).toBe(expected);
  });

  it("tolerates blocked storage and missing matchMedia", () => {
    runStartup({
      get localStorage() {
        throw new Error("Blocked");
      },
    });
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("uses an external blocking head script before the app, without inline code", () => {
    const page = new DOMParser().parseFromString(html, "text/html");
    const script = page.head.querySelector('script[src="/theme-init.js"]');
    expect(script).not.toBeNull();
    expect(script?.hasAttribute("async")).toBe(false);
    expect(script?.hasAttribute("defer")).toBe(false);
    expect(script?.textContent).toBe("");
    expect(html.indexOf("/theme-init.js")).toBeLessThan(html.indexOf("/src/main.tsx"));
  });
});
