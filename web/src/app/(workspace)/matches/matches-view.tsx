"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Money, ModelName, When } from "@/components/format";
import { ErrorNotice, Loading, SuccessNotice } from "@/components/notices";
import { PageHeading } from "@/components/tour/help-button";
import { api, idempotencyKey, unwrap } from "@/lib/api/client";
import { LooseObjectSchema, MatchQueueSchema, VariantListSchema, type MatchQueue } from "@/lib/api/schemas";
import { ATTRIBUTE_FA, MATCH_STATE_FA, label } from "@/lib/labels";

type Pending = MatchQueue["matches"][number];

const STATE_STYLE: Record<string, string> = {
  equal: "",
  different: "bg-red-100 font-semibold text-red-900",
  missing_offer: "text-slate-500",
  missing_ours: "text-slate-500",
};
const STATE_FA: Record<string, string> = {
  equal: "یکسان",
  different: "متفاوت",
  missing_offer: "در آگهی نیست",
  missing_ours: "در کاتالوگ ما نیست",
};

function SideBySide({ match, anchor }: { match: Pending; anchor?: string }) {
  return (
    <table className="data-table data-table-compact" aria-label="مقایسه ویژگی‌ها" data-tour={anchor}>
      <thead>
        <tr className="text-slate-600">
          <th>ویژگی</th>
          <th>کالای ما</th>
          <th>آگهی رقیب</th>
          <th>مقایسه</th>
        </tr>
      </thead>
      <tbody>
        {match.attributes.map((a) => (
          <tr key={a.name} className={STATE_STYLE[a.state]} data-attribute={a.name} data-state={a.state}>
            <td>{label(ATTRIBUTE_FA, a.name)}</td>
            <td>
              <bdi dir="auto">{a.ours ?? "—"}</bdi>
            </td>
            <td>
              <bdi dir="auto">{a.theirs ?? "—"}</bdi>
              {a.source === "llm" && <span className="ms-1 text-xs text-purple-700">(پیشنهاد هوش مصنوعی)</span>}
            </td>
            <td>{STATE_FA[a.state]}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MatchCard({ match, onDone, first = false }: { match: Pending; onDone: (text: string) => void; first?: boolean }) {
  const [mode, setMode] = useState<"confirm" | "reject" | "reassign" | null>(null);
  const [reason, setReason] = useState("");
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState("");
  const candidates = useQuery({
    queryKey: ["variants", query],
    enabled: mode === "reassign",
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalog/variants", { params: { query: { q: query || undefined, limit: 20 } } }), VariantListSchema),
  });
  const decide = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/matches/{match_version_id}/decision", {
          params: { path: { match_version_id: match.match_version_id } },
          body: {
            action: mode ?? "confirm",
            reason: reason.trim() || null,
            target_variant_id: mode === "reassign" ? target : null,
          },
          headers: idempotencyKey(),
        }),
        LooseObjectSchema,
      ),
    onSuccess: () => onDone(mode === "reject" ? "تطبیق رد شد." : mode === "reassign" ? "تطبیق به کالای دیگر منتقل شد." : "تطبیق تأیید شد."),
  });
  const needsReason = mode === "reject" || mode === "reassign" || match.flags.some((f) => f.startsWith("condition_mismatch"));
  return (
    <article className="flex flex-col gap-2 card p-4" data-tour={first ? "match-list" : undefined} data-match={match.match_version_id}>
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{match.variant.product_name}</span>
        <ModelName>{`${match.variant.brand} ${match.variant.model}`}</ModelName>
        <span className="badge bg-orange-50 text-orange-700 ring-orange-600/20">{label(MATCH_STATE_FA, match.state)}</span>
        <span className="text-xs text-slate-600">
          {match.decided_by === "llm" ? "پیشنهاد هوش مصنوعی" : "قاعده"} · اطمینان {Math.round(match.confidence_bp / 100)}٪
        </span>
      </header>
      <p className="text-sm">
        <a href={match.url} target="_blank" rel="noopener noreferrer" className="link">
          {match.source_name}
        </a>{" "}
        — <bdi>{match.title ?? "—"}</bdi> — <Money rial={match.price_rial} />
        {match.observed_at && (
          <>
            {" "}
            (<When at={match.observed_at} />)
          </>
        )}
      </p>
      {match.reason && <p className="text-xs text-slate-600">{match.reason}</p>}
      <SideBySide match={match} anchor={first ? "match-compare" : undefined} />
      <div className="flex flex-wrap gap-2" data-tour={first ? "match-actions" : undefined}>
        <button type="button" className="btn btn-success" onClick={() => setMode("confirm")}>
          تأیید
        </button>
        <button type="button" className="btn btn-danger" onClick={() => setMode("reject")}>
          رد
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => setMode("reassign")}>
          انتقال به کالای دیگر
        </button>
      </div>
      {mode && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            decide.mutate();
          }}
        >
          {mode === "reassign" && (
            <>
              <input
                aria-label="جست‌وجوی کالا"
                placeholder="جست‌وجوی کالا (SKU، نام یا مدل)"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="field"
              />
              <select
                aria-label="کالای مقصد"
                value={target}
                required
                onChange={(e) => setTarget(e.target.value)}
                className="field"
              >
                <option value="">انتخاب کالا</option>
                {(candidates.data ?? [])
                  .filter((v) => v.id !== match.variant.id)
                  .map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.sku} — {v.product_name}
                    </option>
                  ))}
              </select>
            </>
          )}
          <input
            aria-label="دلیل"
            placeholder={needsReason ? "دلیل (الزامی)" : "دلیل (اختیاری)"}
            required={needsReason}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="field"
          />
          <button type="submit" disabled={decide.isPending} className="self-start btn btn-primary">
            ثبت
          </button>
          <ErrorNotice error={decide.error} />
        </form>
      )}
    </article>
  );
}

function SuggestedOffers({ offers, onDone }: { offers: MatchQueue["suggested_offers"]; onDone: (text: string) => void }) {
  const review = useMutation({
    mutationFn: async ({ id, confirm }: { id: string; confirm: boolean }) =>
      unwrap(
        await api.POST("/api/v1/tracked-offers/{tracked_offer_id}/review", {
          params: { path: { tracked_offer_id: id } },
          body: { decision: confirm ? "confirm" : "dismiss" },
          headers: idempotencyKey(),
        }),
        LooseObjectSchema,
      ),
    onSuccess: (_, { confirm }) => onDone(confirm ? "نشانی تأیید شد و پایش آن زمان‌بندی شد." : "پیشنهاد نشانی کنار گذاشته شد."),
  });
  if (!offers.length) return <p className="empty">پیشنهاد نشانی تازه‌ای نیست.</p>;
  return (
    <ul className="flex flex-col gap-2">
      {offers.map((o) => (
        <li key={o.tracked_offer_id} className="card p-4" data-suggested={o.tracked_offer_id}>
          <div className="font-medium">
            {o.variant.product_name} — {o.source_name}
          </div>
          <a href={o.url} target="_blank" rel="noopener noreferrer" className="link">
            <bdi dir="ltr">{o.url}</bdi>
          </a>
          {o.rationale && <p className="text-sm text-slate-600">{o.rationale}</p>}
          <div className="mt-1 flex gap-2">
            <button type="button" className="btn btn-success" onClick={() => review.mutate({ id: o.tracked_offer_id, confirm: true })}>
              تأیید نشانی
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => review.mutate({ id: o.tracked_offer_id, confirm: false })}>
              کنار گذاشتن
            </button>
          </div>
        </li>
      ))}
      <ErrorNotice error={review.error} />
    </ul>
  );
}

export function MatchesView() {
  const client = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const queue = useQuery({
    queryKey: ["match-queue"],
    queryFn: async () => unwrap(await api.GET("/api/v1/match-queue"), MatchQueueSchema),
  });
  const done = (text: string) => {
    setNotice(text);
    void client.invalidateQueries({ queryKey: ["match-queue"] });
    void client.invalidateQueries({ queryKey: ["queue-summary"] });
  };
  if (queue.isPending) return <Loading />;
  if (queue.error) return <ErrorNotice error={queue.error} />;
  return (
    <section className="page">
      <PageHeading
        title="تأیید تطبیق‌ها"
        subtitle="فقط تطبیق‌های تأییدشده در محاسبه قیمت استفاده می‌شوند."
        tour="matches"
      />
      {notice && <SuccessNotice>{notice}</SuccessNotice>}
      <h2 className="section-title">تطبیق‌های در انتظار</h2>
      {queue.data.matches.length ? (
        queue.data.matches.map((m, i) => <MatchCard key={m.match_version_id} match={m} onDone={done} first={i === 0} />)
      ) : (
        <p className="empty" data-tour="match-list">تطبیق در انتظاری نیست.</p>
      )}
      <div className="flex flex-col gap-3" data-tour="match-suggested">
        <h2 className="section-title">نشانی‌های پیشنهادی</h2>
        <SuggestedOffers offers={queue.data.suggested_offers} onDone={done} />
      </div>
    </section>
  );
}
