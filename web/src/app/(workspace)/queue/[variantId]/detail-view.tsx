"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { AlertBadges, OutcomeBadge, StatusBadge } from "@/components/badges";
import { DecisionCard, DecisionHistory } from "@/components/decision-history";
import { Money, ProductLabel, When } from "@/components/format";
import { ErrorNotice, Loading, SuccessNotice, WarningNotice } from "@/components/notices";
import { HelpButton } from "@/components/tour/help-button";
import { useIsAdmin } from "@/components/viewer-context";
import { ApiError, api, idempotencyKey, unwrap } from "@/lib/api/client";
import {
  DecisionSchema,
  HistorySchema,
  ItemDetailSchema,
  LooseObjectSchema,
  RecheckSchema,
  type Decision,
  type EvidenceRow,
  type ItemDetail,
} from "@/lib/api/schemas";
import { faNumber, parseTomanToRial, toman } from "@/lib/format";
import { DECISION_TYPE_FA, MATCH_STATE_FA, STOCK_FA, TIER_FA, label } from "@/lib/labels";
import { useReviewSession } from "./review-session";
import { TrackedOffers } from "./tracked-offers";

export const DECISION_SAVED_FA = "تصمیم ثبت شد؛ هیچ قیمتی در فروشگاه تغییر نکرد.";
export const OVERRIDE_PENDING_FA =
  "تصمیم ثبت شد. قیمت زیر کف سود نیازمند تأیید مدیر است؛ تا تأیید مدیر، قیمت فروشگاه را تغییر ندهید.";
const RECOMPUTE_TIMEOUT_MS = 60_000;

const FLAG_FA: Record<string, string> = {
  condition_mismatch: "شرایط متفاوت",
  price_outlier: "قیمت پرت",
  outside_competitor_set: "خارج از مجموعه رقبا",
};

function Metric({ label: text, children, strong = false }: { label: string; children: ReactNode; strong?: boolean }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg bg-slate-50 px-3 py-2.5">
      <div className="text-xs font-medium text-slate-500">{text}</div>
      <div className={strong ? "text-lg font-bold text-slate-900" : "font-semibold text-slate-800"}>{children}</div>
    </div>
  );
}

function useDetail(variantId: string, waitingFor: string | null) {
  return useQuery({
    queryKey: ["detail", variantId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/queue/{variant_id}", { params: { path: { variant_id: variantId } } }), ItemDetailSchema),
    // after an evidence action, poll until the recomputed recommendation arrives
    refetchInterval: (query) =>
      waitingFor && query.state.data?.item.recommendation_id === waitingFor ? 2_000 : false,
  });
}

function ReasonForm({
  label: text,
  required = true,
  onSubmit,
  pending,
}: {
  label: string;
  required?: boolean;
  onSubmit: (reason: string) => void;
  pending: boolean;
}) {
  const [reason, setReason] = useState("");
  return (
    <form
      className="mt-1 flex gap-1"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(reason.trim());
      }}
    >
      <input
        aria-label={text}
        placeholder={text}
        value={reason}
        required={required}
        onChange={(e) => setReason(e.target.value)}
        className="w-56 field field-sm"
      />
      <button type="submit" disabled={pending} className="btn btn-primary btn-sm">
        ثبت
      </button>
    </form>
  );
}

function EvidenceActions({
  row,
  onChanged,
  anchor,
}: {
  row: EvidenceRow;
  onChanged: () => void;
  anchor?: string;
}) {
  const [open, setOpen] = useState<"reject" | "confirm" | "outlier" | null>(null);
  const [recheckId, setRecheckId] = useState<string | null>(null);
  const action = useMutation({
    mutationFn: async ({ kind, reason }: { kind: "reject" | "confirm" | "outlier"; reason: string }) => {
      if (kind === "outlier") {
        return unwrap(
          await api.POST("/api/v1/observations/{observation_id}/outlier-confirmation", {
            params: { path: { observation_id: row.observation_id } },
            body: { reason },
            headers: idempotencyKey(),
          }),
          LooseObjectSchema,
        );
      }
      return unwrap(
        await api.POST("/api/v1/matches/{match_version_id}/decision", {
          params: { path: { match_version_id: row.match_version_id } },
          body: { action: kind, reason: reason || null },
          headers: idempotencyKey(),
        }),
        LooseObjectSchema,
      );
    },
    onSuccess: () => {
      setOpen(null);
      onChanged();
    },
  });
  const recheck = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tracked-offers/{tracked_offer_id}/recheck", {
          params: { path: { tracked_offer_id: row.tracked_offer_id } },
          headers: idempotencyKey(),
        }),
        RecheckSchema,
      ),
    onSuccess: (data) => setRecheckId(data.id),
  });
  const recheckStatus = useQuery({
    queryKey: ["recheck", recheckId],
    enabled: recheckId !== null,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/rechecks/{recheck_id}", { params: { path: { recheck_id: recheckId ?? "" } } }), RecheckSchema),
    refetchInterval: (q) => (q.state.data?.status === "pending" ? 2_000 : false),
  });
  useEffect(() => {
    if (recheckStatus.data?.status === "completed") onChanged();
  }, [recheckStatus.data?.status, onChanged]);

  const pendingMatch = row.match_state === "needs_review" || row.match_state === "proposed";
  const conditionMismatch = row.match_flags.some((f) => f.startsWith("condition_mismatch"));
  return (
    <div className="flex flex-col gap-1 text-xs" data-tour={anchor}>
      <div className="flex flex-wrap gap-1">
        <button type="button" className="btn-ghost" onClick={() => setOpen("reject")}>
          رد تطبیق
        </button>
        {pendingMatch && (
          <button type="button" className="btn-ghost" onClick={() => setOpen("confirm")}>
            تأیید تطبیق
          </button>
        )}
        {row.flags.includes("price_outlier") && (
          <button type="button" className="btn-ghost" onClick={() => setOpen("outlier")}>
            تأیید قیمت پرت
          </button>
        )}
        <button type="button" className="btn-ghost" onClick={() => recheck.mutate()} disabled={recheck.isPending}>
          بررسی دوباره
        </button>
      </div>
      {open && (
        <ReasonForm
          label={open === "reject" ? "دلیل رد" : open === "outlier" ? "دلیل تأیید قیمت" : "دلیل هم‌ارزی"}
          required={open !== "confirm" || conditionMismatch}
          pending={action.isPending}
          onSubmit={(reason) => action.mutate({ kind: open, reason })}
        />
      )}
      <ErrorNotice error={action.error ?? recheck.error} />
      {recheckId && (
        <span role="status">
          بررسی دوباره: {recheckStatus.data?.status === "completed" ? "انجام شد" : recheckStatus.data?.status === "failed" ? "ناموفق" : "در صف"}
        </span>
      )}
    </div>
  );
}

function EvidenceTable({ detail, onChanged }: { detail: ItemDetail; onChanged: () => void }) {
  if (detail.inputs_purged) {
    return <WarningNotice>مشاهده‌های این پیشنهاد طبق سیاست نگهداری حذف شده‌اند.</WarningNotice>;
  }
  return (
    <table className="data-table" aria-label="شواهد بازار">
      <thead>
        <tr>
          <th>فروشنده / منبع</th>
          <th>قیمت</th>
          <th>موجودی</th>
          <th>شرایط</th>
          <th>تطبیق</th>
          <th>زمان مشاهده</th>
          <th>وضعیت در محاسبه</th>
          <th>اقدام</th>
        </tr>
      </thead>
      <tbody>
        {detail.evidence.map((row, index) => (
          <tr key={row.observation_id} className="align-top" data-observation={row.observation_id}>
            <td>
              <div className="font-medium text-slate-900">
                <bdi>{row.seller ?? "—"}</bdi>
              </div>
              <a href={row.url} target="_blank" rel="noopener noreferrer" className="link">
                {row.source_name}
              </a>
              {row.evidence.map((e) =>
                e.url ? (
                  <a key={e.id} href={e.url} target="_blank" rel="noopener noreferrer" className="ms-2 text-xs underline">
                    سند ({e.kind})
                  </a>
                ) : (
                  <span key={e.id} className="ms-2 text-xs text-slate-500">
                    سند منقضی‌شده
                  </span>
                ),
              )}
            </td>
            <td>
              <span className="font-semibold">
                <Money rial={row.price_rial} />
              </span>
              {row.is_market_reference && <div className="mt-1 badge bg-brand-50 text-brand-700 ring-brand-500/25">مرجع بازار</div>}
            </td>
            <td>{label(STOCK_FA, row.stock_state)}</td>
            <td className="text-xs">
              {Object.values(row.conditions)
                .filter((v) => typeof v === "string" && v)
                .join(" · ") || "—"}
            </td>
            <td>
              {label(MATCH_STATE_FA, row.match_state)}
              {row.flags.map((f) => (
                <span key={f} className="ms-1 badge bg-amber-50 text-amber-800 ring-amber-600/20">
                  {FLAG_FA[f] ?? f}
                </span>
              ))}
            </td>
            <td>
              <When at={row.observed_at} />
              {row.freshness !== "fresh" && <div className="text-xs text-rose-700">قدیمی</div>}
            </td>
            <td className="text-xs">
              {row.qualifies ? <span className="font-medium text-emerald-700">لحاظ شده</span> : <span className="text-slate-500">{row.reasons_fa.join("؛ ")}</span>}
            </td>
            <td>
              <EvidenceActions row={row} onChanged={onChanged} anchor={index === 0 ? "detail-evidence-actions" : undefined} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

type DecisionType = "accept" | "accept_modified" | "reject" | "defer";

function DecisionForm({
  detail,
  onSaved,
  onStale,
  supersedes,
  onCancel,
}: {
  detail: ItemDetail;
  onSaved: (decision: Decision) => void;
  onStale: () => void;
  /** set when this form corrects an earlier decision (a new record referencing it) */
  supersedes?: Decision;
  onCancel?: () => void;
}) {
  const item = detail.item;
  const [type, setType] = useState<DecisionType>(item.suggested_price_rial !== null ? "accept" : "defer");
  const [reason, setReason] = useState("");
  const [price, setPrice] = useState(item.suggested_price_rial !== null ? String(item.suggested_price_rial / 10) : "");
  const [overrideReason, setOverrideReason] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const accept = type === "accept" || type === "accept_modified";
  const appliedRial = accept ? parseTomanToRial(type === "accept" ? String((item.suggested_price_rial ?? 0) / 10) : price) : null;
  const belowFloor = appliedRial !== null && item.floor_rial !== null && appliedRial < item.floor_rial;

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/recommendations/{recommendation_id}/decisions", {
          params: { path: { recommendation_id: item.recommendation_id } },
          body: {
            type,
            reason,
            applied_price_rial: appliedRial,
            override_reason: belowFloor ? overrideReason : null,
            supersedes_decision_id: supersedes?.id ?? null,
          },
          headers: idempotencyKey(),
        }),
        DecisionSchema,
      ),
    onSuccess: onSaved,
    onError: (error) => {
      if (error instanceof ApiError && error.code === "recommendation_superseded") onStale();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setLocalError(null);
    if (!reason.trim()) return setLocalError("برای ثبت، یادداشت تصمیم را وارد کنید.");
    if (accept && appliedRial === null) return setLocalError("قیمت اعمال‌شده را به تومان وارد کنید.");
    if (belowFloor && !overrideReason.trim()) return setLocalError("برای قیمت زیر کف سود، دلیل استثنا را وارد کنید.");
    save.mutate();
  }

  const types: DecisionType[] = item.suggested_price_rial !== null ? ["accept", "accept_modified", "reject", "defer"] : ["accept_modified", "reject", "defer"];
  return (
    <form
      onSubmit={submit}
      className={supersedes ? "flex flex-col gap-4 rounded-lg border border-brand-100 bg-brand-50/40 p-4" : "card flex flex-col gap-4 p-5"}
      aria-label={supersedes ? "اصلاح تصمیم" : "ثبت تصمیم"}
      data-tour={supersedes ? undefined : "detail-decision"}
    >
      <h2 className="section-title">{supersedes ? "اصلاح تصمیم" : "ثبت تصمیم"}</h2>
      {supersedes && (
        <p className="text-xs leading-5 text-slate-600">
          تصمیم قبلی پاک یا ویرایش نمی‌شود؛ یک تصمیم تازه ثبت می‌شود که به آن اشاره می‌کند و هر دو در تاریخچه می‌مانند.
        </p>
      )}
      <fieldset className="flex flex-wrap gap-3">
        <legend className="sr-only">نوع تصمیم</legend>
        {types.map((t) => (
          <label key={t} className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm has-checked:border-brand-500 has-checked:bg-brand-50 has-checked:text-brand-900">
            <input type="radio" name="type" value={t} checked={type === t} onChange={() => setType(t)} />
            {label(DECISION_TYPE_FA, t)}
          </label>
        ))}
      </fieldset>
      {type === "accept_modified" && (
        <label className="field-label">
          قیمتی که در فروشگاه اعمال کردید (تومان)
          <input
            name="applied_price"
            inputMode="numeric"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="w-48 field"
          />
        </label>
      )}
      {type === "accept" && <p className="text-sm">قیمت اعمال‌شده: {toman(item.suggested_price_rial)}</p>}
      {belowFloor && (
        <label className="field-label">
          <span className="font-medium text-rose-700">
            این قیمت از کف سود ({toman(item.floor_rial)}) پایین‌تر است و تأیید مدیر لازم دارد. دلیل استثنا:
          </span>
          <textarea
            name="override_reason"
            value={overrideReason}
            onChange={(e) => setOverrideReason(e.target.value)}
            className="field"
          />
        </label>
      )}
      <label className="field-label">
        یادداشت تصمیم
        <textarea
          name="reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="field"
        />
      </label>
      {localError && (
        <p role="alert" className="text-rose-700">
          {localError}
        </p>
      )}
      <ErrorNotice error={save.error} />
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={save.isPending} className="btn btn-primary">
          {supersedes ? "ثبت تصمیم اصلاحی" : "ثبت تصمیم"}
        </button>
        {onCancel && (
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            انصراف
          </button>
        )}
      </div>
      <p className="text-xs text-slate-500">این سامانه هیچ قیمتی را در فروشگاه تغییر نمی‌دهد؛ تغییر قیمت را دستی انجام دهید.</p>
    </form>
  );
}

function DecisionPanel({
  decisionId,
  detail,
  onChanged,
  onSaved,
  onStale,
}: {
  decisionId: string;
  detail: ItemDetail;
  onChanged: () => void;
  onSaved: (decision: Decision) => void;
  onStale: () => void;
}) {
  const isAdmin = useIsAdmin();
  const [correcting, setCorrecting] = useState(false);
  const decision = useQuery({
    queryKey: ["decision", decisionId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/decisions/{decision_id}", { params: { path: { decision_id: decisionId } } }), DecisionSchema),
  });
  const review = useMutation({
    mutationFn: async ({ approve, reason }: { approve: boolean; reason: string }) =>
      unwrap(
        await api.POST("/api/v1/decisions/{decision_id}/override-review", {
          params: { path: { decision_id: decisionId } },
          body: { decision: approve ? "approve" : "reject", reason },
          headers: idempotencyKey(),
        }),
        DecisionSchema,
      ),
    onSuccess: () => {
      void decision.refetch();
      onChanged();
    },
  });
  const done = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/decisions/{decision_id}/reported-done", {
          params: { path: { decision_id: decisionId } },
          headers: idempotencyKey(),
        }),
        DecisionSchema,
      ),
    onSuccess: () => {
      void decision.refetch();
      onChanged();
    },
  });
  const [approveOpen, setApproveOpen] = useState<boolean | null>(null);
  if (decision.isPending) return <Loading />;
  if (decision.error) return <ErrorNotice error={decision.error} />;
  const d = decision.data;
  const canReport =
    (d.type === "accept" || d.type === "accept_modified") &&
    !d.outcomes.some((o) => o.stage === "reported_done") &&
    d.status !== "override_rejected" &&
    !d.superseded_by;
  return (
    <section className="card flex flex-col gap-3 p-5" aria-label="تصمیم فعلی" data-tour="detail-decision">
      <h2 className="section-title">تصمیم ثبت‌شده</h2>
      <DecisionCard decision={d} />
      {d.status === "override_pending" && isAdmin && (
        <div className="flex flex-col gap-1">
          <div className="flex gap-2">
            <button type="button" className="btn btn-success" onClick={() => setApproveOpen(true)}>
              تأیید قیمت زیر کف
            </button>
            <button type="button" className="btn btn-danger" onClick={() => setApproveOpen(false)}>
              رد قیمت زیر کف
            </button>
          </div>
          {approveOpen !== null && (
            <ReasonForm
              label="دلیل تصمیم مدیر"
              pending={review.isPending}
              onSubmit={(reason) => review.mutate({ approve: approveOpen, reason })}
            />
          )}
        </div>
      )}
      {d.status === "override_rejected" && (
        <p className="text-sm text-rose-800">مدیر قیمت زیر کف را رد کرده است؛ قیمت فروشگاه را تغییر ندهید و تصمیم تازه‌ای ثبت کنید.</p>
      )}
      <div className="flex flex-wrap gap-2">
        {canReport && (
          <button type="button" onClick={() => done.mutate()} disabled={done.isPending} className="btn btn-secondary">
            قیمت را در فروشگاه تغییر دادم
          </button>
        )}
        {!d.superseded_by && !correcting && (
          <button type="button" className={d.status === "override_rejected" ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setCorrecting(true)}>
            {d.status === "override_rejected" ? "ثبت تصمیم تازه" : "اصلاح تصمیم"}
          </button>
        )}
      </div>
      <ErrorNotice error={review.error ?? done.error} />
      {correcting && (
        <DecisionForm
          detail={detail}
          supersedes={d}
          onCancel={() => setCorrecting(false)}
          onSaved={(saved) => {
            setCorrecting(false);
            onSaved(saved);
          }}
          onStale={onStale}
        />
      )}
    </section>
  );
}

export function DetailView({ variantId }: { variantId: string }) {
  const client = useQueryClient();
  const [waitingFor, setWaitingFor] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "saved" | "pending" | "stale"; decisionId?: string } | null>(null);
  const detail = useDetail(variantId, waitingFor);
  const history = useQuery({
    queryKey: ["history", variantId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/variants/{variant_id}/history", { params: { path: { variant_id: variantId } } }), HistorySchema),
  });
  const recommendationId = detail.data?.item.recommendation_id;
  const closeSession = useReviewSession(variantId, recommendationId);

  // waiting ends when a new recommendation arrives, or after the timeout
  const recomputing = waitingFor !== null && recommendationId === waitingFor;
  useEffect(() => {
    if (!waitingFor) return;
    const timer = setTimeout(() => setWaitingFor(null), RECOMPUTE_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [waitingFor]);

  if (detail.isPending) return <Loading />;
  if (detail.error) return <ErrorNotice error={detail.error} />;
  const data = detail.data;
  const item = data.item;

  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["detail", variantId] });
    void client.invalidateQueries({ queryKey: ["history", variantId] });
    void client.invalidateQueries({ queryKey: ["queue"] });
    void client.invalidateQueries({ queryKey: ["queue-summary"] });
  };
  const afterEvidenceAction = () => {
    setWaitingFor(item.recommendation_id);
    refresh();
  };
  const onDecisionSaved = (decision: Decision) => {
    setNotice({ kind: decision.status === "override_pending" ? "pending" : "saved", decisionId: decision.id });
    void closeSession(decision.id);
    refresh();
  };
  const onStale = () => {
    setNotice({ kind: "stale" });
    refresh();
  };

  return (
    <article className="page">
      <div className="flex items-center justify-between gap-3">
        <Link href="/queue" className="link text-sm">
          → بازگشت به صف
        </Link>
        <HelpButton tour="detail" />
      </div>
      <header className="flex flex-col gap-2" data-tour="detail-header">
        <h1 className="page-title">{item.product_name}</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
          <ProductLabel brand={item.brand} model={item.model} attributes={item.attributes} />
          <span className="badge bg-white text-slate-700 ring-slate-300">اهمیت {label(TIER_FA, item.tier)}</span>
          <StatusBadge status={item.status} />
          <AlertBadges alerts={item.alerts} />
        </div>
      </header>

      {notice?.kind === "saved" && <SuccessNotice>{DECISION_SAVED_FA}</SuccessNotice>}
      {notice?.kind === "pending" && <WarningNotice>{OVERRIDE_PENDING_FA}</WarningNotice>}
      {notice?.kind === "stale" && (
        <WarningNotice>پیشنهاد قیمت در این فاصله تغییر کرده است؛ نسخه جدید نمایش داده شد. دوباره بررسی و ثبت کنید.</WarningNotice>
      )}
      {recomputing && (
        <p role="status" className="flex items-center gap-2 text-sm text-brand-700">
          <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-brand-100 border-t-brand-600" />
          در حال محاسبه دوباره پیشنهاد…
        </p>
      )}

      <section className="card grid grid-cols-2 gap-3 p-5 md:grid-cols-4" aria-label="پیشنهاد" data-tour="detail-proposal">
        <h2 className="section-title col-span-full">پیشنهاد قیمت</h2>
        <Metric label="نتیجه">
          <OutcomeBadge outcome={item.outcome} />
        </Metric>
        <Metric label="قیمت ما">
          <Money rial={item.our_price_rial} />
        </Metric>
        <Metric label="مرجع بازار">
          <Money rial={item.market_ref_rial} />
        </Metric>
        <Metric label="قیمت پیشنهادی" strong>
          <Money rial={item.suggested_price_rial} />
        </Metric>
        <Metric label="کف سود">
          <Money rial={item.floor_rial} />
        </Metric>
        <Metric label="سقف">
          <Money rial={item.ceiling_rial} />
        </Metric>
        <Metric label="سود واحد فعلی / پیشنهادی">
          <Money rial={data.profit_current_rial} /> / <Money rial={data.profit_suggested_rial} />
        </Metric>
        <Metric label="محاسبه">
          <When at={item.evaluated_at} />
        </Metric>
        <p className="col-span-full rounded-lg border border-brand-100 bg-brand-50/60 px-4 py-3 text-sm leading-7 text-slate-800" data-testid="explanation" data-tour="detail-explanation">
          {data.explanation_llm ?? data.explanation}
        </p>
        {data.explanation_llm && (
          <details className="col-span-full text-sm text-slate-600">
            <summary>متن دقیق محاسبه</summary>
            {data.explanation}
          </details>
        )}
        <p className="col-span-full text-xs text-slate-500" title="ورودی‌های امتیاز اولویت">
          امتیاز اولویت {faNumber(item.score.score)} — نتیجه {faNumber(item.score.outcome_weight)}، اثر سود{" "}
          {faNumber(item.score.profit_points)}، قدمت {faNumber(item.score.age_points)}، ضریب اهمیت{" "}
          {faNumber(item.score.tier_multiplier)}
        </p>
      </section>

      <section className="flex flex-col gap-2" data-tour="detail-evidence">
        <h2 className="section-title">شواهد بازار</h2>
        <EvidenceTable detail={data} onChanged={afterEvidenceAction} />
      </section>

      <TrackedOffers variantId={variantId} />

      {data.decision && data.decision.recommendation_id === item.recommendation_id ? (
        <DecisionPanel
          key={data.decision.id}
          decisionId={data.decision.id}
          detail={data}
          onChanged={refresh}
          onSaved={onDecisionSaved}
          onStale={onStale}
        />
      ) : (
        <DecisionForm key={item.recommendation_id} detail={data} onSaved={onDecisionSaved} onStale={onStale} />
      )}

      <section className="flex flex-col gap-2" data-tour="detail-history">
        <h2 className="section-title">تاریخچه</h2>
        {history.isPending ? <Loading /> : history.error ? <ErrorNotice error={history.error} /> : <DecisionHistory history={history.data} />}
      </section>
    </article>
  );
}
