import { describe, expect, it } from "vitest";
import { EMPTY_FILTERS, filtersToQuery } from "./queries";

describe("filtersToQuery", () => {
  it("defines empty filters and serializes them to an empty string", () => {
    expect(EMPTY_FILTERS).toEqual({ start: null, end: null, categories: [], regions: [], channels: [] });
    expect(filtersToQuery(EMPTY_FILTERS)).toBe("");
  });

  it.each([
    { start: "2026-01-01", end: null },
    { start: null, end: "2026-01-31" },
    { start: "2026-01-01", end: "2026-01-31" },
  ])("serializes date bounds $start to $end", ({ start, end }) => {
    const params = new URLSearchParams(filtersToQuery({ ...EMPTY_FILTERS, start, end }));
    expect(params.get("start")).toBe(start);
    expect(params.get("end")).toBe(end);
    expect([...params.keys()]).toHaveLength(Number(start !== null) + Number(end !== null));
  });

  it("preserves repeated category, region, and channel values in order", () => {
    const filters = {
      ...EMPTY_FILTERS,
      categories: ["Food", "Books", "Food"],
      regions: ["South", "North", "South"],
      channels: ["Online", "Store", "Online"],
    };
    const params = new URLSearchParams(filtersToQuery(filters));
    expect(params.getAll("category")).toEqual(filters.categories);
    expect(params.getAll("region")).toEqual(filters.regions);
    expect(params.getAll("channel")).toEqual(filters.channels);
  });

  it("URL-encodes special characters without splitting parameter values", () => {
    const query = filtersToQuery({
      ...EMPTY_FILTERS,
      categories: ["Food & Drink"],
      regions: ["North/South"],
      channels: ["Web + App"],
    });
    expect(query).toBe("category=Food+%26+Drink&region=North%2FSouth&channel=Web+%2B+App");
    const params = new URLSearchParams(query);
    expect(params.getAll("category")).toEqual(["Food & Drink"]);
    expect(params.getAll("region")).toEqual(["North/South"]);
    expect(params.getAll("channel")).toEqual(["Web + App"]);
  });
});
