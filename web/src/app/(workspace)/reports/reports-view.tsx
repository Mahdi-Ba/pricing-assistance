"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { z } from "zod";
import { FaNum, Money, When } from "@/components/format";
import { ErrorNotice, Loading } from "@/components/notices";
import { PageHeading } from "@/components/tour/help-button";
import { useIsAdmin } from "@/components/viewer-context";
import { api, idempotencyKey, unwrap } from "@/lib/api/client";
import {
  AuditSchema,
  BaselineSchema,
  LooseObjectSchema,
  PilotReportSchema,
  WeeklyReportSchema,
  type KpiValue,
  type PilotReport,
} from "@/lib/api/schemas";
import { faNumber, minutes, percent } from "@/lib/format";
import { STATUS_FA, VERDICT_FA, label } from "@/lib/labels";

const KPI_FA: Record<string, string> = {
  tier_a_coverage_pct: "پوشش کالاهای اهمیت الف",
  tier_a_data_age_p90_minutes: "قدمت داده اهمیت الف (صدک ۹۰)",
  verification_reliability_pct: "اطمینان مشاهده روی سایت در مهلت",
  source_success_rate_pct: "نرخ موفقیت دریافت از منابع",
};

const LLM_TASK_FA: Record<string, string> = {
  extract_attributes: "استخراج ویژگی‌ها",
  propose_match: "پیشنهاد تطبیق",
  rephrase_explanation: "بازنویسی توضیح",
  suggest_extraction_rule: "پیشنهاد قاعده استخراج",
  suggest_offer_urls: "پیشنهاد نشانی آگهی",
};

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function monday(d: Date): string {
  const copy = new Date(d);
  copy.setUTCDate(copy.getUTCDate() - ((copy.getUTCDay() + 6) % 7));
  return isoDate(copy);
}

/** A measured value next to its target; "هدف تعیین نشده" when none is set. */
function Measured({
  title,
  value,
  target,
  sample,
  lowSample = false,
}: {
  title: string;
  value: string;
  target: string | null;
  sample: string;
  lowSample?: boolean;
}) {
  return (
    <div className="card flex flex-col gap-2 p-4" data-kpi={title}>
      <div className="text-sm font-medium text-slate-500">{title}</div>
      <div className="text-3xl font-bold text-slate-900">{value}</div>
      <div className="text-xs leading-5 text-slate-500">
        هدف: {target ?? "هدف تعیین نشده"} · نمونه: {sample}
        {lowSample && <span className="ms-1 badge bg-amber-50 text-amber-800 ring-amber-600/20">نمونه کم</span>}
      </div>
    </div>
  );
}

function kpiValue(kpi: KpiValue): string {
  if (kpi.value === null) return "—";
  return kpi.unit === "%" ? percent(kpi.value) : `${faNumber(kpi.value, true)} ${kpi.unit === "min" ? "دقیقه" : kpi.unit}`;
}

function Pilot({ report }: { report: PilotReport }) {
  const accuracy = report.match_accuracy;
  const review = report.review_time;
  return (
    <section className="flex flex-col gap-4" aria-label="شاخص‌های آزمایشی">
      <h2 className="section-title">شاخص‌های اصلی آزمایش</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4" data-tour="reports-pilot">
        <Measured
          title="دقت تطبیق"
          value={accuracy ? percent(accuracy.overall.accuracy_pct) : "—"}
          target={accuracy ? `≥ ${percent(accuracy.target_pct)}` : "≥ ۹۸٪"}
          sample={accuracy ? `${faNumber(accuracy.overall.reviewed)} از ${faNumber(accuracy.size)} (${accuracy.period})` : "نمونه‌ای گرفته نشده"}
        />
        <Measured
          title="پیشنهاد زیر کف سود"
          value={faNumber(report.floor_safety.below_floor_suggestions)}
          target={faNumber(report.floor_safety.target)}
          sample={`${faNumber(report.floor_safety.recommendations)} پیشنهاد`}
        />
        <Measured
          title="کامل بودن شواهد"
          value={percent(report.evidence_completeness.completeness_pct)}
          target={percent(report.evidence_completeness.target_pct)}
          sample={`${faNumber(report.evidence_completeness.actionable)} پیشنهاد قابل اقدام`}
        />
        <Measured
          title="کاهش زمان بررسی"
          value={review.reduction_pct !== null ? percent(Math.round(review.reduction_pct)) : "—"}
          target={`≥ ${percent(review.target_pct)}`}
          sample={`${faNumber(review.decisions)} تصمیم`}
          lowSample={review.low_sample}
        />
      </div>
      <div className="flex flex-col gap-4" data-tour="reports-review">
      <h3 className="section-title text-sm">زمان بررسی به تفکیک دسته</h3>
      {review.categories.length === 0 ? (
        <p className="empty">هنوز تصمیمی در این بازه ثبت نشده است.</p>
      ) : (
      <table className="data-table data-table-compact" aria-label="زمان بررسی">
        <thead>
          <tr>
            <th>دسته</th>
            <th>تصمیم‌ها</th>
            <th>میانه</th>
            <th>صدک ۹۰</th>
            <th>مبنای پیش از آزمایش</th>
          </tr>
        </thead>
        <tbody>
          {review.categories.map((c) => (
            <tr key={c.category} className="border-t">
              <td>{c.category}</td>
              <td>
                <FaNum value={c.decisions} />
                {c.low_sample && <span className="ms-1 badge bg-amber-50 text-amber-800 ring-amber-600/20">نمونه کم</span>}
              </td>
              <td>{minutes(c.median_seconds)}</td>
              <td>{minutes(c.p90_seconds)}</td>
              <td>{c.baseline_seconds !== null ? minutes(c.baseline_seconds) : "ثبت نشده"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      )}
      <h3 className="section-title text-sm">قیمت‌های زیر کف (استثنا)</h3>
      {report.floor_safety.overrides.length === 0 ? (
        <p className="empty">موردی نیست.</p>
      ) : (
        <table className="data-table data-table-compact" aria-label="استثناهای زیر کف">
          <thead>
            <tr>
              <th>درخواست‌کننده</th>
              <th>قیمت / کف</th>
              <th>دلیل</th>
              <th>بررسی مدیر</th>
            </tr>
          </thead>
          <tbody>
            {report.floor_safety.overrides.map((o) => (
              <tr key={o.decision_id} className="border-t">
                <td>
                  <bdi>{o.requested_by}</bdi> — <When at={o.decided_at} />
                </td>
                <td>
                  <Money rial={o.applied_price_rial} /> / <Money rial={o.floor_rial} />
                </td>
                <td>{o.request_reason}</td>
                <td>
                  {o.verdict ? `${label(VERDICT_FA, o.verdict)} — ${o.approver ?? ""}: ${o.review_reason ?? ""}` : "در انتظار"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      </div>
    </section>
  );
}

function AuditAdmin({ sampleId }: { sampleId: string | null }) {
  const client = useQueryClient();
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [notes, setNotes] = useState<Record<string, string>>({});
  const audit = useQuery({
    queryKey: ["audit", sampleId],
    enabled: sampleId !== null,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reports/match-audits/{sample_id}", { params: { path: { sample_id: sampleId ?? "" } } }), AuditSchema),
  });
  const draw = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/reports/match-audits", { body: { period, size: 200 }, headers: idempotencyKey() }), AuditSchema),
    onSuccess: () => client.invalidateQueries({ queryKey: ["pilot"] }),
  });
  const verdict = useMutation({
    mutationFn: async ({ id, correct }: { id: string; correct: boolean }) =>
      unwrap(
        await api.POST("/api/v1/reports/match-audit-items/{item_id}/verdict", {
          params: { path: { item_id: id } },
          body: { verdict: correct ? "correct" : "incorrect", note: notes[id] || null },
          headers: idempotencyKey(),
        }),
        LooseObjectSchema,
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["audit", sampleId] });
      void client.invalidateQueries({ queryKey: ["pilot"] });
    },
  });
  const open = audit.data?.items.filter((i) => i.verdict === null) ?? [];
  return (
    <section className="card flex flex-col gap-3 p-5" aria-label="نمونه بررسی تطبیق" data-tour="reports-audit">
      <h2 className="section-title">بررسی ماهانه دقت تطبیق</h2>
      <div className="flex items-end gap-2">
        <label className="field-label">
          ماه (YYYY-MM)
          <input value={period} onChange={(e) => setPeriod(e.target.value)} dir="ltr" className="field" />
        </label>
        <button type="button" onClick={() => draw.mutate()} disabled={draw.isPending} className="btn btn-primary">
          گرفتن نمونه
        </button>
      </div>
      <ErrorNotice error={draw.error ?? verdict.error ?? audit.error} />
      {audit.data && (
        <p className="text-sm">
          نمونه {audit.data.period}: <FaNum value={audit.data.size} /> از <FaNum value={audit.data.population} /> — بررسی‌شده{" "}
          <FaNum value={audit.data.overall.reviewed} />، نادرست <FaNum value={audit.data.incorrect.length} />
        </p>
      )}
      <ul className="flex flex-col gap-1 text-sm">
        {open.slice(0, 20).map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-2">
            <bdi className="text-xs">{i.match_version_id}</bdi> ({i.category}، {i.confidence_band})
            <input aria-label="یادداشت" value={notes[i.id] ?? ""} onChange={(e) => setNotes({ ...notes, [i.id]: e.target.value })} className="field field-sm" />
            <button type="button" className="btn btn-success btn-sm" onClick={() => verdict.mutate({ id: i.id, correct: true })}>
              درست
            </button>
            <button type="button" className="btn btn-danger btn-sm" onClick={() => verdict.mutate({ id: i.id, correct: false })}>
              نادرست
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Baselines() {
  const client = useQueryClient();
  const [category, setCategory] = useState("");
  const [value, setValue] = useState("");
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/reports/baselines/{category}", {
          params: { path: { category } },
          body: { median_minutes: Number(value) },
          headers: idempotencyKey(),
        }),
        LooseObjectSchema,
      ),
    onSuccess: () => {
      setCategory("");
      setValue("");
      void client.invalidateQueries({ queryKey: ["pilot"] });
      void client.invalidateQueries({ queryKey: ["baselines"] });
    },
  });
  const baselines = useQuery({
    queryKey: ["baselines"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reports/baselines"), z.array(BaselineSchema)),
  });
  return (
    <>
    {baselines.data && baselines.data.length > 0 ? (
      <table className="data-table data-table-compact" aria-label="مبناهای ثبت‌شده">
        <thead>
          <tr>
            <th>دسته</th>
            <th>میانه پیش از آزمایش</th>
            <th>ثبت</th>
            <th>اقدام</th>
          </tr>
        </thead>
        <tbody>
          {baselines.data.map((b) => (
            <tr key={b.category}>
              <td>{b.category}</td>
              <td>{minutes(b.median_seconds)}</td>
              <td>
                <bdi>{b.entered_by}</bdi> — <When at={b.created_at} />
              </td>
              <td>
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => {
                    setCategory(b.category);
                    setValue(String(Math.round((b.median_seconds / 60) * 10) / 10));
                  }}
                >
                  ویرایش
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    ) : baselines.data ? (
      <p className="empty">هنوز مبنایی ثبت نشده است.</p>
    ) : null}
    <ErrorNotice error={baselines.error} />
    <form
      className="flex flex-wrap items-end gap-2"
      aria-label="مبنای زمان بررسی"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="field-label">
        دسته
        <input required value={category} onChange={(e) => setCategory(e.target.value)} className="field" />
      </label>
      <label className="field-label">
        میانه زمان پیش از آزمایش (دقیقه)
        <input required inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} className="field" />
      </label>
      <button type="submit" className="btn btn-primary">
        ثبت مبنا
      </button>
      <ErrorNotice error={save.error} />
    </form>
    </>
  );
}

export function ReportsView() {
  const isAdmin = useIsAdmin();
  const today = new Date();
  const [from, setFrom] = useState(isoDate(new Date(today.getTime() - 30 * 86_400_000)));
  const [to, setTo] = useState(isoDate(today));
  const [week, setWeek] = useState(monday(today));
  const pilot = useQuery({
    queryKey: ["pilot", from, to],
    queryFn: async () => unwrap(await api.GET("/api/v1/reports/pilot", { params: { query: { from, to } } }), PilotReportSchema),
  });
  const weekly = useQuery({
    queryKey: ["weekly", week],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reports/weekly", { params: { query: { week_start: week } } }), WeeklyReportSchema),
  });
  return (
    <section className="page">
      <PageHeading
        title="گزارش‌ها"
        subtitle="مقادیر اندازه‌گیری‌شده جدا از هدف‌ها و همراه با اندازه نمونه نمایش داده می‌شوند."
        tour="reports"
      />
      <div className="card flex flex-wrap items-end gap-3 p-4" data-tour="reports-range">
        <label className="field-label">
          از
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="field" />
        </label>
        <label className="field-label">
          تا
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="field" />
        </label>
      </div>
      {pilot.isPending ? <Loading /> : pilot.error ? <ErrorNotice error={pilot.error} /> : <Pilot report={pilot.data} />}

      <section className="flex flex-col gap-4" aria-label="گزارش هفتگی" data-tour="reports-weekly">
        <h2 className="section-title">گزارش هفتگی</h2>
        <label className="field-label">
          شروع هفته
          <input type="date" value={week} onChange={(e) => setWeek(e.target.value)} className="w-48 field" />
        </label>
        {weekly.isPending ? (
          <Loading />
        ) : weekly.error ? (
          <ErrorNotice error={weekly.error} />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              {weekly.data.kpis.map((k) => (
                <Measured
                  key={k.key}
                  title={KPI_FA[k.key] ?? k.key}
                  value={kpiValue(k)}
                  target={k.target !== null ? kpiValue({ ...k, value: k.target }) : null}
                  sample={faNumber(k.sample)}
                />
              ))}
            </div>
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ["تأخیر مشاهده روی سایت (میانه)", minutes(weekly.data.site_delay_seconds.median)],
                ["تأخیر کانال مقایسه (میانه)", minutes(weekly.data.channel_delay_seconds.median)],
                ["زمان پیشنهاد تا تصمیم (میانه)", minutes(weekly.data.recommendation_to_decision_seconds.median)],
                [
                  "صف باز",
                  Object.entries(weekly.data.backlog)
                    .map(([status, count]) => `${label(STATUS_FA, status)}: ${faNumber(count)}`)
                    .join("، ") || "—",
                ],
              ].map(([term, value]) => (
                <div key={term} className="rounded-lg border border-slate-200 bg-white px-4 py-3">
                  <dt className="text-xs text-slate-500">{term}</dt>
                  <dd className="mt-1 font-semibold text-slate-800">{value}</dd>
                </div>
              ))}
            </dl>
            <h3 className="section-title text-sm">منابع در این هفته</h3>
            <table className="data-table data-table-compact" aria-label="منابع هفته">
              <thead>
                <tr>
                  <th>منبع</th>
                  <th>درخواست</th>
                  <th>موفقیت</th>
                  <th>مسدود</th>
                  <th>هزینه</th>
                </tr>
              </thead>
              <tbody>
                {weekly.data.sources.map((s) => (
                  <tr key={s.source_id} className="border-t">
                    <td>{s.name}</td>
                    <td>
                      <FaNum value={s.requests} />
                    </td>
                    <td>{s.success_rate !== null ? percent(s.success_rate * 100) : "—"}</td>
                    <td>
                      <FaNum value={s.blocked} />
                    </td>
                    <td>
                      <Money rial={s.estimated_cost_rial} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 className="section-title text-sm">مصرف هوش مصنوعی</h3>
            {weekly.data.llm.length === 0 ? (
              <p className="empty">در این هفته از هوش مصنوعی استفاده نشده است.</p>
            ) : (
            <table className="data-table data-table-compact" aria-label="مصرف هوش مصنوعی">
              <thead>
                <tr>
                  <th>کار</th>
                  <th>مدل</th>
                  <th>فراخوانی (موفق)</th>
                  <th>توکن ورودی / خروجی</th>
                  <th>هزینه</th>
                </tr>
              </thead>
              <tbody>
                {weekly.data.llm.map((u) => (
                  <tr key={`${u.task}-${u.model}`} className="border-t">
                    <td>{LLM_TASK_FA[u.task] ?? u.task}</td>
                    <td>
                      <bdi dir="ltr">{u.model}</bdi>
                    </td>
                    <td>
                      <FaNum value={u.calls} /> (<FaNum value={u.ok} />)
                    </td>
                    <td>
                      <FaNum value={u.input_tokens} /> / <FaNum value={u.output_tokens} />
                    </td>
                    <td>{u.cost_rial !== null ? <Money rial={u.cost_rial} /> : "قیمت تعیین نشده"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </>
        )}
      </section>
      {isAdmin && (
        <>
          <AuditAdmin sampleId={pilot.data?.match_accuracy?.sample_id ?? null} />
          <section className="card flex flex-col gap-3 p-5" data-tour="reports-baselines">
            <h2 className="section-title">مبنای زمان بررسی هر دسته</h2>
            <Baselines />
          </section>
        </>
      )}
    </section>
  );
}
