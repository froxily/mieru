import * as React from "react";
import type { DataTableProps } from "./DataTable.types";

export function DataTable<Row>({ columns, rows, rowKey, caption, initialSort, maxHeight, emptyMessage, dense }: DataTableProps<Row>) {
  const [sort, setSort] = React.useState(initialSort);
  const sortedRows = React.useMemo(() => {
    const indexedRows = rows.map((row, index) => ({ row, index }));
    const sortValue = columns.find((column) => column.key === sort?.key)?.sortValue;
    if (!sort || !sortValue) return indexedRows;

    return indexedRows.sort((a, b) => {
      const left = sortValue(a.row);
      const right = sortValue(b.row);
      if (left == null && right == null) return a.index - b.index;
      if (left == null) return 1;
      if (right == null) return -1;
      const comparison = typeof left === "number" && typeof right === "number" ? left - right : String(left).localeCompare(String(right));
      return (sort.direction === "asc" ? comparison : -comparison) || a.index - b.index;
    });
  }, [rows, columns, sort]);

  return (
    <div className="table-wrap" style={{ maxHeight, overflow: maxHeight !== undefined ? "auto" : undefined }}>
      <table className={dense ? "table table-dense" : "table"}>
        {caption !== undefined && <caption className="visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => {
              const direction = sort?.key === column.key ? sort.direction : undefined;
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={column.align === "right" ? "num" : undefined}
                  style={{ width: column.width }}
                  aria-sort={column.sortValue ? (direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none") : undefined}
                >
                  {column.sortValue ? (
                    <button
                      type="button"
                      onClick={() =>
                        setSort((current) => ({
                          key: column.key,
                          direction: current?.key === column.key && current.direction === "desc" ? "asc" : "desc",
                        }))
                      }
                    >
                      {column.header} <small aria-hidden="true">{direction === "asc" ? "▲" : direction === "desc" ? "▼" : "↕"}</small>
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="muted">
                {emptyMessage ?? "No rows to display"}
              </td>
            </tr>
          ) : (
            sortedRows.map(({ row, index }) => (
              <tr key={rowKey(row, index)}>
                {columns.map((column) => (
                  <td key={column.key} className={column.align === "right" ? "num" : undefined}>
                    {column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
