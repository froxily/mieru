import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { KpiCard } from "./KpiCard";
import { MetricDebuggerProvider } from "./MetricDebugger";

describe("KpiCard", () => {
  it("immediately renders the label, compact currency value, and full formatted title", () => {
    render(<KpiCard label="Revenue" value={15423084.73} unit="currency" currency="BRL" />);
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("R$ 15.42M")).toHaveAttribute("title", "R$ 15,423,085");
  });

  it("does not offer a calculation button without a metric reference", () => {
    render(<KpiCard label="Orders" value={2400} unit="count" />);
    expect(screen.queryByRole("button", { name: "How is Orders calculated?" })).not.toBeInTheDocument();
  });

  it("shows the unavailable reason instead of the value", () => {
    render(<KpiCard label="Revenue" value={15423084.73} unit="currency" currency="BRL" status="unavailable" unavailableReason="No amount column was found." />);
    expect(screen.getByText("No amount column was found.")).toBeInTheDocument();
    expect(screen.queryByText("R$ 15.42M")).not.toBeInTheDocument();
    expect(screen.queryByTitle("R$ 15,423,085")).not.toBeInTheDocument();
  });

  it("opens the metric debugger through its provider when the calculation button is clicked", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(() => {}));
    const view = render(
      <QueryClientProvider client={client}>
        <MetricDebuggerProvider>
          <KpiCard
            label="Revenue"
            value={15423084.73}
            unit="currency"
            currency="BRL"
            metric={{ source: "dataset", datasetId: "sales-2026", metricId: "revenue" }}
          />
        </MetricDebuggerProvider>
      </QueryClientProvider>,
    );
    try {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "How is Revenue calculated?" }));
      const dialog = screen.getByRole("dialog", { name: "Metric" });
      expect(dialog).toHaveAttribute("aria-modal", "true");
      expect(dialog).toHaveTextContent("revenue");
    } finally {
      view.unmount();
      client.clear();
      fetchMock.mockRestore();
    }
  });
});
