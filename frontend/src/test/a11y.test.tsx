import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { useRef, useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { DatasetDashboard, DatasetStatusPayload } from "../api/datasetTypes";
import { AppShell } from "../components/AppShell";
import { Segmented } from "../components/Card";
import { DataTable } from "../components/DataTable";
import { KpiCard } from "../components/KpiCard";
import { MetricDebuggerProvider } from "../components/MetricDebugger";
import { ClarificationsBanner, ExportMenu, ProcessingView } from "../features/datasets/DatasetChrome";
import { FiltersBar } from "../features/datasets/FiltersBar";
import { EMPTY_FILTERS } from "../features/datasets/queries";
import { useFocusTrap } from "../lib/useFocusTrap";

const COMPONENT_RULES = { "color-contrast": { enabled: false }, region: { enabled: false } };

async function violations(container: HTMLElement, rules: Record<string, { enabled: boolean }> = COMPONENT_RULES): Promise<string[]> {
  const results = await axe.run(container, { rules });
  return results.violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(" ")).join(", ")}`);
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function client(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
}

const processing: DatasetStatusPayload = {
  dataset: {
    dataset_id: "sales-2026",
    display_name: "October sales.csv",
    status: "processing",
    stage: "mapping",
    error: null,
    created_at: "2026-10-26T00:00:00Z",
    expires_at: "2026-10-27T00:00:00Z",
    size_bytes: 2400,
    data_version: 1,
  },
  stages: ["uploaded", "decoding", "profiling", "mapping", "cleaning", "analytics", "ready"],
};

const dashboard = {
  filters: {
    applied: EMPTY_FILTERS,
    options: { categories: ["Tools", "Toys"], regions: ["Tokyo"], channels: ["Web"], date_min: "2024-01-01", date_max: "2024-12-31" },
  },
} as unknown as DatasetDashboard;

beforeAll(() => {
  if (typeof window.matchMedia !== "function") {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("axe-core accessibility checks", () => {
  it("app shell has landmarks, a skip link and a named menu toggle", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/api/datasets")) return Promise.resolve(jsonResponse({ datasets: [] }));
      return Promise.resolve(jsonResponse({ kpis: [], dataset: { currency: "BRL" } }));
    });
    const view = render(
      <QueryClientProvider client={client()}>
        <MemoryRouter initialEntries={["/olist/overview"]}>
          <AppShell>
            <h1>Executive overview</h1>
          </AppShell>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", "#main-content");
    expect(screen.getByRole("button", { name: "Menu" })).toHaveAttribute("aria-expanded", "false");
    expect(document.title).toBe("Executive overview · MIERU");
    expect(await violations(view.container, { "color-contrast": { enabled: false } })).toEqual([]);
  });

  it("KPI card, segmented control and sortable table", async () => {
    const view = render(
      <div>
        <KpiCard label="Revenue" value={1200} unit="currency" currency="JPY" />
        <Segmented
          value="a"
          options={[
            { value: "a", label: "Category" },
            { value: "b", label: "Product" },
          ]}
          onChange={() => undefined}
          label="Dimension"
        />
        <DataTable
          rows={[{ name: "Tools", value: 3 }]}
          rowKey={(row) => row.name}
          caption="Example table"
          columns={[
            { key: "name", header: "Name", sortValue: (row) => row.name },
            { key: "value", header: "Value", align: "right", sortValue: (row) => row.value },
          ]}
        />
      </div>,
    );
    expect(screen.getByRole("button", { name: "Category" })).toHaveAttribute("aria-pressed", "true");
    expect(await violations(view.container)).toEqual([]);
  });

  it("dataset chrome: processing view, clarifications and filters", async () => {
    const view = render(
      <MemoryRouter>
        <ProcessingView status={processing} />
        <ClarificationsBanner
          assumptions={["One unit per row."]}
          clarifications={[{ kind: "ambiguous_role", role: "order_total", label: "Order total", columns: ["amount"], message: "Check the amount column." }]}
        />
        <FiltersBar dashboard={dashboard} filters={EMPTY_FILTERS} onChange={() => undefined} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Step 4 of 6/)).toHaveAttribute("aria-live", "polite");
    expect(await violations(view.container)).toEqual([]);
  });

  it("open export menu", async () => {
    const user = userEvent.setup();
    const view = render(<ExportMenu datasetId="sales-2026" query="" />);
    await user.click(screen.getByRole("button", { name: "Export" }));
    expect(screen.getByRole("menu", { name: "Export formats" })).toBeInTheDocument();
    expect(await violations(view.container)).toEqual([]);
  });

  it("open metric debugger drawer", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(() => {}));
    const view = render(
      <QueryClientProvider client={client()}>
        <MetricDebuggerProvider>
          <KpiCard
            label="Revenue"
            value={1200}
            unit="currency"
            currency="JPY"
            metric={{ source: "dataset", datasetId: "sales-2026", metricId: "net_revenue" }}
          />
        </MetricDebuggerProvider>
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole("button", { name: "How is Revenue calculated?" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(await violations(view.baseElement as HTMLElement)).toEqual([]);
  });
});

function TrapHarness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      {open && <Dialog onClose={() => setOpen(false)} />}
    </div>
  );
}

function Dialog({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useFocusTrap(ref);
  return (
    <div ref={ref} role="dialog" aria-label="Example">
      <button type="button">First</button>
      <button type="button" onClick={onClose}>
        Last
      </button>
    </div>
  );
}

describe("keyboard behaviour", () => {
  it("focus trap wraps Tab and Shift+Tab and restores focus to the opener", async () => {
    const user = userEvent.setup();
    render(<TrapHarness />);
    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);
    screen.getByRole("button", { name: "Last" }).focus();
    await user.tab();
    expect(screen.getByRole("button", { name: "First" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Last" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Last" }));
    expect(opener).toHaveFocus();
  });

  it("export menu supports arrows, Home/End and Escape back to the trigger", async () => {
    const user = userEvent.setup();
    render(<ExportMenu datasetId="sales-2026" query="" />);
    const trigger = screen.getByRole("button", { name: "Export" });
    await user.click(trigger);
    const items = screen.getAllByRole("menuitem");
    expect(items[0]).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(items[1]).toHaveFocus();
    await user.keyboard("{End}");
    expect(items[items.length - 1]).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(items[0]).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(items[items.length - 1]).toHaveFocus();
    await user.keyboard("{Home}");
    expect(items[0]).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
