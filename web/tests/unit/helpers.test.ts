import { describe, expect, test } from "vitest";
import { fromApi, toApi } from "@/app/(workspace)/rules/rules-view";
import { cardHref, filtersFrom, toSearchParams } from "@/lib/queue-filters";

describe("queue filters in the URL", () => {
  test("round trip and card drill-down links", () => {
    const filters = filtersFrom(new URLSearchParams("status=needs_review&tier=A&tier=B&ignored=1"));
    expect(filters).toEqual({ status: ["needs_review"], tier: ["A", "B"] });
    expect(toSearchParams(filters).toString()).toBe("tier=A&tier=B&status=needs_review");
    expect(cardHref({ price_position: "above_market" })).toBe("/queue?price_position=above_market");
    expect(cardHref({ status: ["needs_review"] })).toBe("/queue?status=needs_review");
    expect(cardHref({})).toBe("/queue");
  });
});

describe("rule editor units", () => {
  test("percent, Toman and minutes convert to the API units", () => {
    expect(toApi("percent", "10")).toBe(1_000);
    expect(toApi("percent", "۱۰")).toBe(1_000);
    expect(toApi("toman", "50,000")).toBe(500_000);
    expect(toApi("minutes", "120")).toBe(7_200);
    expect(toApi("count", "")).toBeNull();
    expect(fromApi("percent", 1_500)).toBe("15");
    expect(fromApi("minutes", 14_400)).toBe("240");
    expect(fromApi("toman", null)).toBe("");
  });
});
