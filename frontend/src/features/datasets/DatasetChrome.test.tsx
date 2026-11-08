import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Clarification, DatasetStatusPayload } from "../../api/datasetTypes";
import { ClarificationsBanner, DatasetTabs, ProcessingView, SchemaBadges } from "./DatasetChrome";

const status: DatasetStatusPayload = {
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

const clarification: Clarification = {
  kind: "missing",
  role: "currency",
  label: "Currency",
  columns: [],
  message: "Choose a currency for this file.",
};

describe("ProcessingView", () => {
  it("shows the file heading and marks completed, current, and upcoming stages", () => {
    render(
      <MemoryRouter>
        <ProcessingView status={status} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: status.dataset.display_name })).toBeInTheDocument();
    const progress = screen.getByRole("list", { name: "Processing progress" });
    const steps = within(progress).getAllByRole("listitem");
    expect(steps.map((step) => step.textContent)).toEqual([
      "File received",
      "Reading & decoding",
      "Profiling columns",
      "Detecting column roles",
      "Cleaning & checking quality",
      "Building dashboards",
    ]);
    steps.slice(0, 3).forEach((step) => {
      expect(step).toHaveClass("done");
      expect(step).not.toHaveClass("active");
    });
    const active = within(progress).getByText("Detecting column roles");
    expect(active).toHaveClass("active");
    expect(active).not.toHaveClass("done");
    steps.slice(4).forEach((step) => {
      expect(step).not.toHaveClass("done");
      expect(step).not.toHaveClass("active");
    });
    expect(within(progress).queryByText(/^ready$/i)).not.toBeInTheDocument();
  });
});

describe("ClarificationsBanner", () => {
  it("renders nothing when both arrays are empty", () => {
    const { container } = render(
      <MemoryRouter>
        <ClarificationsBanner assumptions={[]} clarifications={[]} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows clarification and assumption messages with the attention title and can be dismissed", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MemoryRouter>
        <ClarificationsBanner assumptions={["Each row represents one line item."]} clarifications={[clarification]} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Some things need your attention")).toBeInTheDocument();
    expect(screen.getByText(clarification.message)).toBeInTheDocument();
    expect(screen.getByText("Each row represents one line item.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(container).toBeEmptyDOMElement();
  });

  it("uses the interpretation title when only the assumptions array has entries", () => {
    render(
      <MemoryRouter>
        <ClarificationsBanner assumptions={["Dates use day/month/year."]} clarifications={[]} />
      </MemoryRouter>,
    );
    expect(screen.getByText("How MIERU interpreted this file")).toBeInTheDocument();
    expect(screen.getByText("Dates use day/month/year.")).toBeInTheDocument();
    expect(screen.queryByText("Some things need your attention")).not.toBeInTheDocument();
  });

  it("uses the informational title for an assumption-only clarification", () => {
    const assumption = { ...clarification, kind: "assumption", message: "Amounts are interpreted as revenue." };
    render(
      <MemoryRouter>
        <ClarificationsBanner assumptions={[]} clarifications={[assumption]} />
      </MemoryRouter>,
    );
    expect(screen.getByText("How MIERU interpreted this file")).toBeInTheDocument();
    expect(screen.queryByText("Some things need your attention")).not.toBeInTheDocument();
    expect(screen.getByText(assumption.message)).toBeInTheDocument();
  });
});

describe("SchemaBadges", () => {
  it("formats rows, labels line-item grain, and identifies an unspecified currency", () => {
    render(
      <MemoryRouter>
        <SchemaBadges rows={2400} grain="line" basis={null} currency={null} />
      </MemoryRouter>,
    );
    expect(screen.getByText("2,400 rows")).toBeInTheDocument();
    expect(screen.getByText("Line-item file")).toBeInTheDocument();
    expect(screen.getByText("Currency not specified")).toBeInTheDocument();
  });
});

describe("DatasetTabs", () => {
  it.each(["dashboard", "quality"] as const)("marks only the %s link as the current page", (active) => {
    render(
      <MemoryRouter>
        <DatasetTabs datasetId="sales-2026" active={active} />
      </MemoryRouter>,
    );
    const navigation = screen.getByRole("navigation", { name: "Dataset views" });
    const dashboard = within(navigation).getByRole("link", { name: "Dashboard" });
    const quality = within(navigation).getByRole("link", { name: "Data quality" });
    expect(dashboard).toHaveAttribute("href", "/data/sales-2026");
    expect(quality).toHaveAttribute("href", "/data/sales-2026/quality");
    const current = active === "dashboard" ? dashboard : quality;
    const other = active === "dashboard" ? quality : dashboard;
    expect(current).toHaveAttribute("aria-current", "page");
    expect(other).not.toHaveAttribute("aria-current");
  });
});
