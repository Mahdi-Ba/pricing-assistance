/**
 * Typed API client for the browser. Calls go to the same-origin BFF (`/api/backend/...`), which
 * adds the user's token server-side. Paths and bodies are typed from the OpenAPI schema;
 * responses are validated with Zod before use.
 */
import createClient from "openapi-fetch";
import type { z } from "zod";
import type { paths } from "./schema";
import { ProblemSchema } from "./schemas";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly messageFa: string,
    readonly body: unknown,
  ) {
    super(`${status} ${code}`);
  }
}

const GENERIC_FA = "خطایی رخ داد؛ دوباره تلاش کنید.";
const INVALID_FA = "پاسخ سرور قابل‌استفاده نبود؛ دوباره تلاش کنید.";

export function createApi(baseUrl = "/api/backend") {
  return createClient<paths>({
    baseUrl,
    headers: { accept: "application/json" },
    credentials: "same-origin",
  });
}

export const api = createApi();

/** A fresh idempotency key for a state-changing request (one per user action). */
export function idempotencyKey(): Record<string, string> {
  return { "Idempotency-Key": crypto.randomUUID() };
}

export function toApiError(status: number, error: unknown): ApiError {
  const problem = ProblemSchema.safeParse(error);
  if (problem.success) {
    const code = problem.data.type.split(":").pop() ?? "error";
    return new ApiError(status, code, problem.data.message_fa ?? GENERIC_FA, problem.data);
  }
  return new ApiError(status, "error", GENERIC_FA, error);
}

/** Unwrap an openapi-fetch result: throw ApiError on failure, validate the body on success. */
export function unwrap<S extends z.ZodType>(
  result: { data?: unknown; error?: unknown; response: Response },
  schema: S,
): z.infer<S> {
  if (!result.response.ok || result.error !== undefined) {
    throw toApiError(result.response.status, result.error);
  }
  const parsed = schema.safeParse(result.data);
  if (!parsed.success) {
    throw new ApiError(result.response.status, "invalid_response", INVALID_FA, parsed.error.issues);
  }
  return parsed.data;
}

/** Unwrap a call that answers without a body (204): throw ApiError on failure. */
export function unwrapEmpty(result: { error?: unknown; response: Response }): void {
  if (!result.response.ok || result.error !== undefined) {
    throw toApiError(result.response.status, result.error);
  }
}
