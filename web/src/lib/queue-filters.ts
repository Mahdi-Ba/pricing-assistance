/** Queue filters ⇄ URL search params (shareable views; the same keys the API takes). */

export const FILTER_KEYS = ["category", "tier", "outcome", "status", "source_health", "price_position"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type Filters = Partial<Record<FilterKey, string[]>>;

export function filtersFrom(params: URLSearchParams): Filters {
  const filters: Filters = {};
  for (const key of FILTER_KEYS) {
    const values = params.getAll(key).filter(Boolean);
    if (values.length) filters[key] = values;
  }
  return filters;
}

export function toSearchParams(filters: Filters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    for (const value of filters[key] ?? []) params.append(key, value);
  }
  return params;
}

/** Card filters arrive as {key: value | value[]}; produce the queue URL for a drill-down. */
export function cardHref(filter: Record<string, string | string[]>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filter)) {
    for (const v of Array.isArray(value) ? value : [value]) params.append(key, v);
  }
  const query = params.toString();
  return query ? `/queue?${query}` : "/queue";
}
