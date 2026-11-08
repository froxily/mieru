import type { ReactNode } from "react";

export type SortDirection = "asc" | "desc";

export interface DataTableColumn<Row> {
  key: string;
  header: string;
  align?: "left" | "right";
  render?: (row: Row) => ReactNode;
  sortValue?: (row: Row) => number | string | null | undefined;
  width?: string;
}

export interface DataTableProps<Row> {
  columns: DataTableColumn<Row>[];
  rows: Row[];
  rowKey: (row: Row, index: number) => string;
  caption?: string;
  initialSort?: { key: string; direction: SortDirection };
  maxHeight?: number;
  emptyMessage?: string;
  dense?: boolean;
}
