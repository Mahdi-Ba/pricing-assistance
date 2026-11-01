/**
 * Contract test of the typed client against a mock API server: typed paths, Zod validation of
 * responses, problem+json mapping to Persian messages.
 */
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { ApiError, createApi, unwrap } from "@/lib/api/client";
import { CardsSchema, QueuePageSchema } from "@/lib/api/schemas";

const ITEM = {
  variant_id: "01a17500-0000-7000-8000-000000000001",
  sku: "SSD-1",
  product_name: "Samsung 990 PRO",
  brand: "Samsung",
  model: "990 PRO",
  category: "ssd",
  tier: "A",
  attributes: { capacity: "1TB" },
  recommendation_id: "01a17500-0000-7000-8000-000000000002",
  outcome: "floor_conflict",
  reason_code: "market_below_floor",
  flags: [],
  our_price_rial: 90_000_000,
  market_ref_rial: 80_000_000,
  market_label: null,
  suggested_price_rial: null,
  floor_rial: 84_000_000,
  ceiling_rial: null,
  evaluated_at: "2026-10-26T08:00:00Z",
  status: "needs_review",
  decision_id: null,
  alerts: ["floor_conflict"],
  score: {
    score: 450,
    tier_multiplier: 3,
    outcome_weight: 100,
    profit_impact_rial: 10_000_000,
    profit_points: 20,
    open_since: "2026-10-26T07:00:00Z",
    age_hours: 1,
    age_points: 1,
  },
};

const routes: Record<string, [number, unknown]> = {
  "/api/v1/queue": [200, { items: [ITEM], total: 1, next_cursor: null }],
  "/api/v1/queue/summary": [200, [{ key: "open_decisions", title_fa: "تصمیم‌های باز", count: "three" }]],
  "/api/v1/queue/missing": [
    404,
    { type: "urn:pricing-assistance:problem:not_found", title: "Not found", status: 404, message_fa: "برای این کالا پیشنهادی وجود ندارد." },
  ],
};

let server: Server;
let base: string;
const seen: { url: string; method: string }[] = [];

beforeAll(async () => {
  server = createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://x");
    seen.push({ url: url.pathname + url.search, method: req.method ?? "" });
    const [status, body] = routes[url.pathname] ?? [404, { type: "x", status: 404 }];
    res.writeHead(status, { "content-type": status < 400 ? "application/json" : "application/problem+json" });
    res.end(JSON.stringify(body));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(() => {
  server.close();
});

describe("typed API client", () => {
  test("valid responses are parsed and typed; query parameters are serialized", async () => {
    const api = createApi(base);
    const page = unwrap(
      await api.GET("/api/v1/queue", { params: { query: { status: ["needs_review", "decided"], tier: ["A"] } } }),
      QueuePageSchema,
    );
    expect(page.items[0]?.outcome).toBe("floor_conflict");
    expect(page.items[0]?.score.score).toBe(450);
    expect(seen.at(-1)?.url).toContain("status=needs_review&status=decided");
  });

  test("a response that does not match the schema is rejected", async () => {
    const api = createApi(base);
    const result = await api.GET("/api/v1/queue/summary");
    expect(() => unwrap(result, CardsSchema)).toThrowError(ApiError);
    try {
      unwrap(result, CardsSchema);
    } catch (error) {
      expect((error as ApiError).code).toBe("invalid_response");
    }
  });

  test("problem responses become ApiError with the Persian message", async () => {
    const api = createApi(base);
    const result = await api.GET("/api/v1/queue/{variant_id}", { params: { path: { variant_id: "missing" } } });
    try {
      unwrap(result, QueuePageSchema);
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(404);
      expect((error as ApiError).code).toBe("not_found");
      expect((error as ApiError).messageFa).toBe("برای این کالا پیشنهادی وجود ندارد.");
    }
  });
});
