import type { DatasetDashboard, DatasetFilters } from "../../api/datasetTypes";
import { EMPTY_FILTERS, filtersToQuery } from "./queries";

export function FiltersBar({
  dashboard,
  filters,
  onChange,
}: {
  dashboard: DatasetDashboard;
  filters: DatasetFilters;
  onChange: (filters: DatasetFilters) => void;
}) {
  const options = dashboard.filters.options;
  const active = filtersToQuery(filters) !== "";
  const select = (label: string, key: "categories" | "regions" | "channels", values?: string[]) =>
    values && values.length > 0 ? (
      <div className="field" key={key}>
        <label htmlFor={`filter-${key}`}>{label}</label>
        <select
          id={`filter-${key}`}
          className="select"
          value={filters[key][0] ?? ""}
          onChange={(event) => onChange({ ...filters, [key]: event.target.value ? [event.target.value] : [] })}
        >
          <option value="">All</option>
          {values.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>
    ) : null;
  return (
    <div className="filter-bar" role="search" aria-label="Dashboard filters">
      {options.date_min && (
        <>
          <div className="field">
            <label htmlFor="filter-start">From</label>
            <input
              id="filter-start"
              className="input"
              type="date"
              min={options.date_min}
              max={options.date_max}
              value={filters.start ?? ""}
              onChange={(event) => onChange({ ...filters, start: event.target.value || null })}
            />
          </div>
          <div className="field">
            <label htmlFor="filter-end">To</label>
            <input
              id="filter-end"
              className="input"
              type="date"
              min={options.date_min}
              max={options.date_max}
              value={filters.end ?? ""}
              onChange={(event) => onChange({ ...filters, end: event.target.value || null })}
            />
          </div>
        </>
      )}
      {select("Category", "categories", options.categories)}
      {select("Region", "regions", options.regions)}
      {select("Channel", "channels", options.channels)}
      <div className="topbar-spacer" />
      {active && (
        <button type="button" className="btn btn-ghost" onClick={() => onChange(EMPTY_FILTERS)}>
          Clear filters
        </button>
      )}
    </div>
  );
}
