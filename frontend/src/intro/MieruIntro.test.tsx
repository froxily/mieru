import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { INTRO_STORAGE_KEY, MieruIntro, MieruSplash } from "./MieruIntro";
import { FAILSAFE } from "./timeline";

function endAnimation(element: Element, animationName: string) {
  // React selects the prefixed event when jsdom lacks AnimationEvent.
  const type = !("AnimationEvent" in window) && "WebkitAnimation" in document.documentElement.style ? "webkitAnimationEnd" : "animationend";
  const event = new Event(type, { bubbles: true });
  Object.defineProperty(event, "animationName", { value: animationName });
  fireEvent(element, event);
}

beforeEach(() => {
  sessionStorage.clear();
  document.documentElement.removeAttribute("data-intro");
});

afterEach(() => {
  vi.useRealTimers();
  sessionStorage.clear();
  document.documentElement.removeAttribute("data-intro");
});

describe("MieruIntro", () => {
  it("renders a Skip intro button, an aria-hidden decorative scene, and the tagline", () => {
    const view = render(<MieruIntro onFinish={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Skip intro" })).toBeInTheDocument();
    expect(view.container.querySelector(".mi-scene")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("See beyond the spreadsheet.")).toBeInTheDocument();
  });

  it("waits for the skip animation to finish and calls onFinish only once", async () => {
    const user = userEvent.setup();
    const onFinish = vi.fn();
    render(<MieruIntro onFinish={onFinish} />);
    const overlay = screen.getByRole("presentation");

    await user.click(screen.getByRole("button", { name: "Skip intro" }));

    expect(overlay).toHaveClass("is-skipping");
    expect(onFinish).not.toHaveBeenCalled();
    endAnimation(overlay, "mi-skip");
    expect(onFinish).toHaveBeenCalledTimes(1);
    endAnimation(overlay, "mi-skip");
    expect(onFinish).toHaveBeenCalledTimes(1);
  });

  it("starts skipping when Escape is pressed on window", () => {
    const onFinish = vi.fn();
    render(<MieruIntro onFinish={onFinish} />);

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.getByRole("presentation")).toHaveClass("is-skipping");
    expect(onFinish).not.toHaveBeenCalled();
  });

  it("starts skipping when the overlay background is clicked", async () => {
    const user = userEvent.setup();
    const onFinish = vi.fn();
    render(<MieruIntro onFinish={onFinish} />);
    const overlay = screen.getByRole("presentation");

    await user.click(overlay);

    expect(overlay).toHaveClass("is-skipping");
    expect(onFinish).not.toHaveBeenCalled();
  });

  it.each(["mi-exit", "mi-reduced"])("finishes on the root's %s animation and ignores child or unrelated animations", (animationName) => {
    const onFinish = vi.fn();
    render(<MieruIntro onFinish={onFinish} />);
    const overlay = screen.getByRole("presentation");
    const bar = overlay.querySelector(".mi-bar")!;

    endAnimation(bar, "mi-morph");
    endAnimation(bar, animationName);
    endAnimation(overlay, "mi-morph");
    expect(onFinish).not.toHaveBeenCalled();

    endAnimation(overlay, animationName);
    expect(onFinish).toHaveBeenCalledTimes(1);
    endAnimation(overlay, animationName);
    expect(onFinish).toHaveBeenCalledTimes(1);
  });

  it("finishes exactly once at FAILSAFE without animation events", () => {
    vi.useFakeTimers();
    const onFinish = vi.fn();
    render(<MieruIntro onFinish={onFinish} />);

    act(() => vi.advanceTimersByTime(FAILSAFE - 1));
    expect(onFinish).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(onFinish).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(FAILSAFE));
    endAnimation(screen.getByRole("presentation"), "mi-exit");
    expect(onFinish).toHaveBeenCalledTimes(1);
  });

  it("has no axe-core accessibility violations", async () => {
    const view = render(<MieruIntro onFinish={vi.fn()} />);

    const results = await axe.run(view.container, {
      rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
    });

    expect(results.violations).toEqual([]);
  });
});

describe("MieruSplash", () => {
  it("shows the intro on the first visit, records the session, and removes the finished overlay", () => {
    expect(sessionStorage.getItem(INTRO_STORAGE_KEY)).toBeNull();
    const view = render(<MieruSplash />);

    expect(screen.getByRole("button", { name: "Skip intro" })).toBeInTheDocument();
    expect(sessionStorage.getItem(INTRO_STORAGE_KEY)).toBe("1");

    endAnimation(screen.getByRole("presentation"), "mi-exit");

    expect(view.container).toBeEmptyDOMElement();
    expect(screen.queryByRole("button", { name: "Skip intro" })).not.toBeInTheDocument();
  });

  it("renders nothing when the session already contains the intro key", () => {
    sessionStorage.setItem(INTRO_STORAGE_KEY, "1");

    const view = render(<MieruSplash />);

    expect(view.container).toBeEmptyDOMElement();
    expect(screen.queryByRole("button", { name: "Skip intro" })).not.toBeInTheDocument();
  });

  it.each([false, true])("removes the pre-paint data-intro attribute on mount with a seen session of %s", (seen) => {
    if (seen) sessionStorage.setItem(INTRO_STORAGE_KEY, "1");
    document.documentElement.setAttribute("data-intro", "");

    const view = render(<MieruSplash />);

    expect(document.documentElement).not.toHaveAttribute("data-intro");
    if (seen) {
      expect(view.container).toBeEmptyDOMElement();
    } else {
      expect(screen.getByRole("button", { name: "Skip intro" })).toBeInTheDocument();
    }
  });

  it("does not replay after rerendering a finished splash", () => {
    const view = render(<MieruSplash />);
    endAnimation(screen.getByRole("presentation"), "mi-exit");
    expect(view.container).toBeEmptyDOMElement();

    view.rerender(<MieruSplash tagline="A new route's tagline" />);

    expect(view.container).toBeEmptyDOMElement();
    expect(sessionStorage.getItem(INTRO_STORAGE_KEY)).toBe("1");
  });

  it("does not replay after unmounting and mounting a fresh splash in the same session", () => {
    const first = render(<MieruSplash />);
    endAnimation(screen.getByRole("presentation"), "mi-exit");
    expect(first.container).toBeEmptyDOMElement();
    first.unmount();

    const next = render(<MieruSplash />);

    expect(next.container).toBeEmptyDOMElement();
    expect(sessionStorage.getItem(INTRO_STORAGE_KEY)).toBe("1");
  });

  it("keeps the app underneath inert until the intro finishes", () => {
    render(
      <>
        <MieruSplash />
        <main id="main-content">Dashboard</main>
      </>,
    );
    const main = screen.getByText("Dashboard");

    expect(main).toHaveAttribute("inert");
    endAnimation(screen.getByRole("presentation"), "mi-exit");
    expect(main).not.toHaveAttribute("inert");
  });

  it("releases the app as soon as skipping starts and fades from the current opacity", async () => {
    const user = userEvent.setup();
    render(
      <>
        <MieruSplash />
        <main id="main-content">Dashboard</main>
      </>,
    );
    const overlay = screen.getByRole("presentation");

    await user.click(screen.getByRole("button", { name: "Skip intro" }));

    expect(screen.getByText("Dashboard")).not.toHaveAttribute("inert");
    expect(overlay.style.getPropertyValue("--mi-skip-from")).not.toBe("");
    endAnimation(overlay, "mi-skip");
    expect(overlay).not.toBeInTheDocument();
  });

  it("leaves elements that were already inert untouched", () => {
    render(
      <>
        <MieruSplash />
        <div inert>Already inert</div>
      </>,
    );

    endAnimation(screen.getByRole("presentation"), "mi-exit");

    expect(screen.getByText("Already inert")).toHaveAttribute("inert");
  });
});
