import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DataTable } from "./DataTable";
import type { DataTableColumn } from "./DataTable.types";

interface Row {
  name: string;
  amount: number | null | undefined;
}

const columns: DataTableColumn<Row>[] = [
  { key: "name", header: "Name", sortValue: (row) => row.name },
  { key: "amount", header: "Amount", align: "right", sortValue: (row) => row.amount },
  { key: "details", header: "Details", render: (row) => <strong>{row.name} details</strong> },
];
const rowKey = (row: Row) => row.name;

function rowNames() {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0]?.textContent);
}

describe("DataTable", () => {
  it("renders headers, rows, a caption, numeric alignment, and custom cells", () => {
    render(<DataTable columns={columns} rows={[{ name: "Alpha", amount: 0 }]} rowKey={rowKey} caption="Sales" dense maxHeight={240} />);

    const table = screen.getByRole("table", { name: "Sales" });
    expect(table).toHaveClass("table", "table-dense");
    expect(table.parentElement).toHaveClass("table-wrap");
    expect(table.parentElement).toHaveStyle({ maxHeight: "240px", overflow: "auto" });
    expect(screen.getByText("Sales")).toHaveClass("visually-hidden");
    expect(screen.getAllByRole("columnheader")).toHaveLength(3);
    expect(screen.getByRole("columnheader", { name: "Name" })).toHaveAttribute("scope", "col");
    expect(screen.getByRole("columnheader", { name: "Amount" })).toHaveClass("num");
    expect(screen.getByRole("cell", { name: "0" })).toHaveClass("num");
    expect(screen.getByRole("cell", { name: "Alpha details" }).querySelector("strong")).toHaveTextContent("Alpha details");
    expect(screen.getByRole("columnheader", { name: "Details" })).not.toHaveAttribute("aria-sort");
    expect(screen.queryByRole("button", { name: "Details" })).not.toBeInTheDocument();
    expect(rowNames()).toEqual(["Alpha"]);
  });

  it("sorts numerically descending, ascending, then descending and updates aria-sort", async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        columns={columns}
        rows={[
          { name: "Two", amount: 2 },
          { name: "Ten", amount: 10 },
          { name: "One", amount: 1 },
        ]}
        rowKey={rowKey}
      />,
    );
    const header = screen.getByRole("columnheader", { name: "Amount" });
    const button = screen.getByRole("button", { name: "Amount" });
    expect(button).toHaveAttribute("type", "button");
    expect(header).toHaveAttribute("aria-sort", "none");
    expect(within(button).getByText("↕")).toHaveAttribute("aria-hidden", "true");

    await user.click(button);
    expect(rowNames()).toEqual(["Ten", "Two", "One"]);
    expect(header).toHaveAttribute("aria-sort", "descending");
    expect(within(button).getByText("▼")).toHaveAttribute("aria-hidden", "true");
    await user.click(button);
    expect(rowNames()).toEqual(["One", "Two", "Ten"]);
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(within(button).getByText("▲")).toHaveAttribute("aria-hidden", "true");
    await user.click(button);
    expect(rowNames()).toEqual(["Ten", "Two", "One"]);
    expect(header).toHaveAttribute("aria-sort", "descending");
  });

  it("keeps null and undefined last and equal values stable in both directions", async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        columns={columns}
        rows={[
          { name: "Null", amount: null },
          { name: "First", amount: 2 },
          { name: "Undefined", amount: undefined },
          { name: "Low", amount: 1 },
          { name: "Second", amount: 2 },
        ]}
        rowKey={rowKey}
      />,
    );
    expect(screen.getAllByRole("cell", { name: "—" })).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Amount" }));
    expect(rowNames()).toEqual(["First", "Second", "Low", "Null", "Undefined"]);
    await user.click(screen.getByRole("button", { name: "Amount" }));
    expect(rowNames()).toEqual(["Low", "First", "Second", "Null", "Undefined"]);
  });

  it("honors initialSort and starts a newly selected string column descending", async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        columns={columns}
        rows={[
          { name: "Beta", amount: 2 },
          { name: "Alpha", amount: 1 },
        ]}
        rowKey={rowKey}
        initialSort={{ key: "amount", direction: "asc" }}
      />,
    );
    expect(rowNames()).toEqual(["Alpha", "Beta"]);
    expect(screen.getByRole("columnheader", { name: "Amount" })).toHaveAttribute("aria-sort", "ascending");
    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(rowNames()).toEqual(["Beta", "Alpha"]);
    expect(screen.getByRole("columnheader", { name: "Name" })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: "Amount" })).toHaveAttribute("aria-sort", "none");
    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(rowNames()).toEqual(["Alpha", "Beta"]);
  });

  it.each([undefined, "No matching sales"])("renders the empty state with message %s", (emptyMessage) => {
    render(<DataTable columns={columns} rows={[]} rowKey={rowKey} emptyMessage={emptyMessage} />);
    expect(screen.getAllByRole("row")).toHaveLength(2);
    const cell = screen.getByRole("cell", { name: emptyMessage ?? "No rows to display" });
    expect(cell).toHaveClass("muted");
    expect(cell).toHaveAttribute("colspan", "3");
  });

  it("does not mutate the input array or its rows while sorting", async () => {
    const user = userEvent.setup();
    const rows: Row[] = [
      { name: "Low", amount: 1 },
      { name: "High", amount: 10 },
    ];
    const originalRows = rows.map((row) => ({ ...row }));
    rows.forEach(Object.freeze);
    Object.freeze(rows);
    render(<DataTable columns={columns} rows={rows} rowKey={rowKey} initialSort={{ key: "amount", direction: "desc" }} />);
    expect(rowNames()).toEqual(["High", "Low"]);
    expect(rows).toEqual(originalRows);
    await user.click(screen.getByRole("button", { name: "Amount" }));
    expect(rowNames()).toEqual(["Low", "High"]);
    expect(rows).toEqual(originalRows);
  });
});
