"use client";

import { useCallback, useEffect, useRef } from "react";
import { api, unwrap } from "@/lib/api/client";
import { ReviewSessionSchema } from "@/lib/api/schemas";

const ACTIVITY_INTERVAL_MS = 60_000;

/**
 * Review-time measurement (review_session): opened when the detail view mounts, kept alive by
 * user activity, closed on decision or when the view is left. The server closes sessions idle
 * for 15 minutes on its own.
 */
export function useReviewSession(variantId: string, recommendationId: string | undefined) {
  const sessionId = useRef<string | null>(null);
  const lastPing = useRef(0);

  useEffect(() => {
    if (!recommendationId) return;
    let cancelled = false;
    (async () => {
      try {
        const opened = unwrap(
          await api.POST("/api/v1/review-sessions", {
            body: { variant_id: variantId, recommendation_id: recommendationId },
          }),
          ReviewSessionSchema,
        );
        if (!cancelled) sessionId.current = opened.id;
      } catch {
        // timing is best effort; reviewing must never be blocked by it
      }
    })();
    const ping = () => {
      const id = sessionId.current;
      const now = Date.now();
      if (!id || now - lastPing.current < ACTIVITY_INTERVAL_MS) return;
      lastPing.current = now;
      void api.POST("/api/v1/review-sessions/{session_id}/activity", { params: { path: { session_id: id } } });
    };
    window.addEventListener("pointerdown", ping);
    window.addEventListener("keydown", ping);
    return () => {
      cancelled = true;
      window.removeEventListener("pointerdown", ping);
      window.removeEventListener("keydown", ping);
      const id = sessionId.current;
      if (id) {
        sessionId.current = null;
        void fetch(`/api/backend/api/v1/review-sessions/${id}/close`, {
          method: "POST",
          keepalive: true,
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ reason: "left" }),
        });
      }
    };
  }, [variantId, recommendationId]);

  return useCallback(async (decisionId: string) => {
    const id = sessionId.current;
    if (!id) return;
    sessionId.current = null;
    await api.POST("/api/v1/review-sessions/{session_id}/close", {
      params: { path: { session_id: id } },
      body: { reason: "decision", decision_id: decisionId },
    });
  }, []);
}
