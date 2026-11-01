"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { z } from "zod";
import { FaNum, Money, When } from "@/components/format";
import { ErrorNotice, Loading, SuccessNotice } from "@/components/notices";
import { PageHeading } from "@/components/tour/help-button";
import { api, idempotencyKey, toApiError, unwrap, unwrapEmpty } from "@/lib/api/client";
import {
  ClearanceSchema,
  ExtractionRuleSchema,
  LooseObjectSchema,
  QualificationRunSchema,
  SourceHealthSchema,
  SourceSchema,
  type Source,
} from "@/lib/api/schemas";
import { minutes, percent } from "@/lib/format";

const QUALIFICATION_SAMPLE = 20; // the API default
const STATUS_FA: Record<string, string> = {
  candidate: "نامزد",
  under_evaluation: "در حال ارزیابی",
  approved: "تأییدشده",
  suspended: "معلق",
  rejected: "ردشده",
};
const NEXT_STATUSES: Record<string, string[]> = {
  candidate: ["under_evaluation", "rejected"],
  under_evaluation: ["approved", "rejected", "suspended"],
  approved: ["suspended"],
  suspended: ["approved", "under_evaluation", "rejected"],
  rejected: ["candidate"],
};

const METHOD_FA: Record<Source["method"], string> = {
  html: "HTML (صفحه معمولی)",
  rendered_page: "صفحه رندرشده (با مرورگر)",
  api: "API رسمی",
};
/** Connectors the workers know: page connectors read any site; API connectors are per service. */
const CONNECTORS: { key: string; label: string; methods: Source["method"][] }[] = [
  { key: "generic_html", label: "خواننده عمومی صفحه (generic_html)", methods: ["html", "rendered_page"] },
  { key: "torob_shop_api", label: "API فروشگاه ترب (torob_shop_api)", methods: ["api"] },
];
const COLLECTING: Source["status"][] = ["under_evaluation", "approved"];

function connectorsFor(method: Source["method"], current?: string) {
  const known = CONNECTORS.filter((c) => c.methods.includes(method));
  return current && !CONNECTORS.some((c) => c.key === current) ? [...known, { key: current, label: current, methods: [method] }] : known;
}

function Field({ name, label, type = "text", ...rest }: { name: string; label: string; type?: string } & Record<string, unknown>) {
  return (
    <label className="field-label">
      {label}
      <input name={name} type={type} className="field" {...rest} />
    </label>
  );
}

function form(e: FormEvent<HTMLFormElement>): Record<string, string> {
  e.preventDefault();
  return Object.fromEntries(new FormData(e.currentTarget).entries()) as Record<string, string>;
}

function Clearances({ source }: { source: Source }) {
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["clearances", source.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/sources/{source_id}/clearances", { params: { path: { source_id: source.id } } }),
        z.array(ClearanceSchema),
      ),
  });
  const grant = useMutation({
    mutationFn: async (v: Record<string, string>) =>
      unwrap(
        await api.POST("/api/v1/sources/{source_id}/clearances", {
          params: { path: { source_id: source.id } },
          body: {
            approver_name: v.approver_name ?? "",
            approved_on: v.approved_on ?? "",
            scope: v.scope ?? "",
            reference: v.reference ?? "",
            permitted_requests_per_minute: Number(v.permitted_requests_per_minute),
          },
          headers: idempotencyKey(),
        }),
        ClearanceSchema,
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["clearances", source.id] }),
  });
  const revoke = useMutation({
    mutationFn: async (v: Record<string, string>) =>
      unwrap(
        await api.POST("/api/v1/sources/{source_id}/clearances/revoke", {
          params: { path: { source_id: source.id } },
          body: { reason: v.reason ?? "" },
          headers: idempotencyKey(),
        }),
        ClearanceSchema,
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["clearances", source.id] });
      void client.invalidateQueries({ queryKey: ["sources"] });
    },
  });
  const latest = list.data?.toSorted((a, b) => a.created_at.localeCompare(b.created_at)).at(-1);
  return (
    <div className="flex flex-col gap-2">
      <h4 className="font-medium">سوابق مجوز دسترسی</h4>
      {list.isPending ? (
        <Loading />
      ) : list.error ? (
        <ErrorNotice error={list.error} />
      ) : list.data.length === 0 ? (
        <p className="text-sm text-slate-600">هنوز مجوزی ثبت نشده است؛ این منبع دریافت نمی‌شود.</p>
      ) : (
        <ul className="text-sm">
          {list.data.map((c) => (
            <li key={c.id}>
              {c.kind === "granted" ? "اعطا" : "لغو"} — {c.approver_name ?? "—"} — {c.reference ?? "—"} — سقف{" "}
              {c.permitted_requests_per_minute ?? "—"} درخواست در دقیقه — <When at={c.created_at} />
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={(e) => grant.mutate(form(e))} className="flex flex-wrap items-end gap-2" aria-label="ثبت مجوز">
        <Field name="approver_name" label="تأییدکننده" required />
        <Field name="approved_on" label="تاریخ تأیید" type="date" required />
        <Field name="scope" label="دامنه مجوز" required />
        <Field name="reference" label="شماره سند" required />
        <Field name="permitted_requests_per_minute" label="سقف درخواست در دقیقه" type="number" min={1} required />
        <button type="submit" className="btn btn-primary" disabled={grant.isPending}>
          ثبت مجوز
        </button>
      </form>
      <ErrorNotice error={grant.error} />
      {latest?.kind === "granted" && (
        <form
          onSubmit={(e) => revoke.mutate(form(e))}
          className="flex flex-wrap items-end gap-2 rounded-lg border border-rose-200 bg-rose-50/50 p-3"
          aria-label="لغو مجوز"
        >
          <Field name="reason" label="دلیل لغو مجوز" required />
          <button type="submit" className="btn btn-danger" disabled={revoke.isPending}>
            لغو مجوز
          </button>
          <p className="basis-full text-xs text-slate-600">با لغو مجوز، منبع «معلق» می‌شود و دریافت خودکار از آن متوقف می‌شود.</p>
          <ErrorNotice error={revoke.error} />
        </form>
      )}
    </div>
  );
}

/** Edit the registry entry. Collection settings stay fixed while the source is collecting. */
function EditSource({ source }: { source: Source }) {
  const client = useQueryClient();
  const collecting = COLLECTING.includes(source.status);
  const [v, setV] = useState({
    name: source.name,
    base_domain: source.base_domain,
    method: source.method,
    connector_key: source.connector_key,
    currency_unit: source.currency_unit,
    quota_per_minute: String(source.quota_per_minute),
    a: String(source.interval_a_seconds / 60),
    b: String(source.interval_b_seconds / 60),
    c: String(source.interval_c_seconds / 60),
  });
  const save = useMutation({
    mutationFn: async () => {
      const settings = {
        quota_per_minute: Number(v.quota_per_minute),
        interval_a_seconds: Math.round(Number(v.a) * 60),
        interval_b_seconds: Math.round(Number(v.b) * 60),
        interval_c_seconds: Math.round(Number(v.c) * 60),
      };
      const settingsChanged =
        settings.quota_per_minute !== source.quota_per_minute ||
        settings.interval_a_seconds !== source.interval_a_seconds ||
        settings.interval_b_seconds !== source.interval_b_seconds ||
        settings.interval_c_seconds !== source.interval_c_seconds;
      return unwrap(
        await api.PATCH("/api/v1/sources/{source_id}", {
          params: { path: { source_id: source.id } },
          body: {
            name: v.name !== source.name ? v.name : null,
            base_domain: v.base_domain !== source.base_domain ? v.base_domain : null,
            method: v.method !== source.method ? v.method : null,
            connector_key: v.connector_key !== source.connector_key ? v.connector_key : null,
            currency_unit: v.currency_unit !== source.currency_unit ? v.currency_unit : null,
            settings: settingsChanged ? settings : null,
          },
          headers: idempotencyKey(),
        }),
        SourceSchema,
      );
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });
  const set = (key: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [key]: e.target.value });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      className="flex flex-col gap-3"
      aria-label="ویرایش منبع"
      data-tour="sources-edit"
    >
      <h4 className="font-medium">ویرایش منبع</h4>
      {collecting && (
        <p className="text-xs leading-5 text-slate-600">
          این منبع در حال دریافت است؛ دامنه، روش دریافت، کلید رابط و واحد پول فقط پس از «معلق» کردن منبع قابل تغییرند.
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="field-label">
          نام
          <input required value={v.name} onChange={set("name")} className="field" />
        </label>
        <label className="field-label">
          دامنه
          <input required dir="ltr" value={v.base_domain} onChange={set("base_domain")} disabled={collecting} className="field disabled:bg-slate-100" />
        </label>
        <label className="field-label">
          روش دریافت
          <select
            value={v.method}
            disabled={collecting}
            onChange={(e) => {
              const method = e.target.value as Source["method"];
              const fits = connectorsFor(method).some((c) => c.key === v.connector_key);
              setV({ ...v, method, connector_key: fits ? v.connector_key : (connectorsFor(method)[0]?.key ?? v.connector_key) });
            }}
            className="field disabled:bg-slate-100"
          >
            {(Object.keys(METHOD_FA) as Source["method"][]).map((m) => (
              <option key={m} value={m}>
                {METHOD_FA[m]}
              </option>
            ))}
          </select>
        </label>
        <label className="field-label">
          کلید رابط
          <select value={v.connector_key} onChange={set("connector_key")} disabled={collecting} className="field disabled:bg-slate-100" dir="ltr">
            {connectorsFor(v.method, source.connector_key).map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field-label">
          واحد پول قیمت‌های منبع
          <select value={v.currency_unit} onChange={set("currency_unit")} disabled={collecting} className="field disabled:bg-slate-100">
            <option value="TOMAN">تومان</option>
            <option value="RIAL">ریال</option>
          </select>
        </label>
        <label className="field-label">
          سهمیه در دقیقه
          <input type="number" min={1} max={600} required value={v.quota_per_minute} onChange={set("quota_per_minute")} className="field" />
        </label>
        <label className="field-label">
          فاصله دریافت اهمیت الف (دقیقه)
          <input type="number" min={1} required value={v.a} onChange={set("a")} className="field" />
        </label>
        <label className="field-label">
          فاصله دریافت اهمیت ب (دقیقه)
          <input type="number" min={1} required value={v.b} onChange={set("b")} className="field" />
        </label>
        <label className="field-label">
          فاصله دریافت اهمیت ج (دقیقه)
          <input type="number" min={1} required value={v.c} onChange={set("c")} className="field" />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className="btn btn-primary" disabled={save.isPending}>
          ذخیره تغییرات
        </button>
        {save.isSuccess && <SuccessNotice>تغییرات منبع ذخیره شد.</SuccessNotice>}
      </div>
      <ErrorNotice error={save.error} />
    </form>
  );
}

/** Only a candidate that was never used can be deleted; the server checks it again. */
function DeleteSource({ source, onDeleted }: { source: Source; onDeleted: () => void }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const remove = useMutation({
    mutationFn: async (v: Record<string, string>) =>
      unwrapEmpty(
        await api.DELETE("/api/v1/sources/{source_id}", {
          params: { path: { source_id: source.id } },
          body: { reason: v.reason ?? "" },
          headers: idempotencyKey(),
        }),
      ),
    onSuccess: () => {
      onDeleted();
      void client.invalidateQueries({ queryKey: ["sources"] });
      void client.invalidateQueries({ queryKey: ["sources-health"] });
    },
  });
  if (source.status !== "candidate") {
    return (
      <p className="text-xs leading-5 text-slate-600" data-tour="sources-delete">
        فقط منبع «نامزد» که هنوز استفاده نشده قابل حذف است. برای کنار گذاشتن این منبع، وضعیت آن را «ردشده» یا «معلق» کنید تا سابقه‌اش حفظ شود.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-tour="sources-delete">
      {!open ? (
        <button type="button" className="btn btn-secondary self-start text-rose-700" onClick={() => setOpen(true)}>
          حذف منبع
        </button>
      ) : (
        <form
          onSubmit={(e) => remove.mutate(form(e))}
          className="flex flex-wrap items-end gap-2 rounded-lg border border-rose-200 bg-rose-50/50 p-3"
          aria-label="حذف منبع"
        >
          <p className="basis-full text-sm text-rose-900">
            «{source.name}» برای همیشه حذف می‌شود. این کار فقط برای منبعی ممکن است که مجوز، آگهی، قاعده یا داده‌ای ندارد.
          </p>
          <Field name="reason" label="دلیل حذف" required />
          <button type="submit" className="btn btn-danger" disabled={remove.isPending}>
            حذف قطعی
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => setOpen(false)}>
            انصراف
          </button>
          <div className="basis-full">
            <ErrorNotice error={remove.error} />
          </div>
        </form>
      )}
    </div>
  );
}

/** Upload a saved product page; new rule versions are validated against these samples. */
function Samples({ source }: { source: Source }) {
  const add = useMutation({
    mutationFn: async (data: FormData) => {
      const response = await fetch(`/api/backend/api/v1/sources/${encodeURIComponent(source.id)}/samples`, {
        method: "POST",
        body: data,
        headers: idempotencyKey(),
      });
      const body: unknown = await response.json();
      if (!response.ok) throw toApiError(response.status, body);
      return body;
    },
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        add.mutate(new FormData(e.currentTarget));
        e.currentTarget.reset();
      }}
      className="flex flex-wrap items-end gap-2"
      aria-label="افزودن نمونه صفحه"
    >
      <Field name="url" label="نشانی صفحه نمونه" required dir="ltr" />
      <label className="field-label">
        فایل HTML صفحه
        <input type="file" name="file" accept=".html,.htm,text/html" required className="field" />
      </label>
      <button type="submit" className="btn btn-secondary" disabled={add.isPending}>
        افزودن نمونه
      </button>
      {add.isSuccess && <SuccessNotice>نمونه صفحه ذخیره شد.</SuccessNotice>}
      <ErrorNotice error={add.error} />
    </form>
  );
}

const RULE_EXAMPLE = JSON.stringify(
  {
    offer_container: ".seller-row",
    price: { selector: ".price" },
    stock: { selector: ".stock", in_stock: ["موجود"], out_of_stock: ["ناموجود"] },
    seller: { selector: ".seller-name" },
  },
  null,
  2,
);

/** Propose a new rule version (CSS selectors as JSON); it is tested on the samples and needs approval. */
function ProposeRule({ source }: { source: Source }) {
  const client = useQueryClient();
  const [text, setText] = useState(RULE_EXAMPLE);
  const [parseError, setParseError] = useState<string | null>(null);
  const propose = useMutation({
    mutationFn: async (config: Record<string, unknown>) =>
      unwrap(
        await api.POST("/api/v1/sources/{source_id}/extraction-rules", {
          params: { path: { source_id: source.id } },
          body: { config },
          headers: idempotencyKey(),
        }),
        ExtractionRuleSchema,
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["extraction-rules", source.id] }),
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setParseError(null);
        try {
          const config: unknown = JSON.parse(text);
          if (!config || typeof config !== "object" || Array.isArray(config)) throw new Error("not an object");
          propose.mutate(config as Record<string, unknown>);
        } catch {
          setParseError("متن قاعده JSON معتبر نیست.");
        }
      }}
      className="flex flex-col gap-2"
      aria-label="پیشنهاد قاعده استخراج"
    >
      <label className="field-label">
        قاعده جدید (انتخابگرهای CSS به صورت JSON)
        <textarea dir="ltr" rows={8} value={text} onChange={(e) => setText(e.target.value)} className="field font-mono text-xs" />
      </label>
      {parseError && (
        <p role="alert" className="text-sm text-rose-700">
          {parseError}
        </p>
      )}
      <button type="submit" className="btn btn-secondary self-start" disabled={propose.isPending}>
        ثبت و آزمون روی نمونه‌ها
      </button>
      {propose.isSuccess && <SuccessNotice>نسخه جدید ثبت شد و پس از تأیید مدیر فعال می‌شود.</SuccessNotice>}
      <ErrorNotice error={propose.error} />
    </form>
  );
}

function StatusChange({ source }: { source: Source }) {
  const client = useQueryClient();
  const change = useMutation({
    mutationFn: async (v: Record<string, string>) =>
      unwrap(
        await api.POST("/api/v1/sources/{source_id}/status", {
          params: { path: { source_id: source.id } },
          body: { status: v.status as Source["status"], reason: v.reason ?? "" },
          headers: idempotencyKey(),
        }),
        SourceSchema,
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });
  return (
    <form onSubmit={(e) => change.mutate(form(e))} className="flex flex-wrap items-end gap-2" aria-label="تغییر وضعیت منبع">
      <label className="field-label">
        وضعیت جدید
        <select name="status" className="field">
          {(NEXT_STATUSES[source.status] ?? []).map((s) => (
            <option key={s} value={s}>
              {STATUS_FA[s]}
            </option>
          ))}
        </select>
      </label>
      <Field name="reason" label="دلیل" required />
      <button type="submit" className="btn btn-primary" disabled={change.isPending}>
        تغییر وضعیت
      </button>
      <ErrorNotice error={change.error} />
    </form>
  );
}

function ExtractionRules({ source }: { source: Source }) {
  const client = useQueryClient();
  const [reason, setReason] = useState("");
  const rules = useQuery({
    queryKey: ["extraction-rules", source.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/sources/{source_id}/extraction-rules", { params: { path: { source_id: source.id } } }),
        z.array(ExtractionRuleSchema),
      ),
  });
  const review = useMutation({
    mutationFn: async ({ id, approve }: { id: string; approve: boolean }) =>
      unwrap(
        await api.POST("/api/v1/extraction-rules/{rule_version_id}/review", {
          params: { path: { rule_version_id: id } },
          body: { decision: approve ? "approve" : "reject", reason },
          headers: idempotencyKey(),
        }),
        ExtractionRuleSchema,
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["extraction-rules", source.id] }),
  });
  if (rules.isPending) return <Loading />;
  if (rules.error) return <ErrorNotice error={rules.error} />;
  return (
    <div className="flex flex-col gap-2">
      <h4 className="font-medium">نسخه‌های قاعده استخراج</h4>
      {rules.data.length === 0 && <p className="text-sm text-slate-600">قاعده‌ای ثبت نشده است.</p>}
      <ul className="flex flex-col gap-2 text-sm">
        {rules.data.map((r) => (
          <li key={r.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3" data-rule={r.id}>
            نسخه <FaNum value={r.version} /> — {r.state === "active" ? "فعال" : r.state === "proposed" ? "پیشنهادی" : r.state === "rejected" ? "ردشده" : "بازنشسته"} —{" "}
            {r.origin === "llm" ? "پیشنهاد هوش مصنوعی" : "مدیر"} — نتیجه نمونه‌ها:{" "}
            {r.validation?.passed ? "موفق" : "ناموفق"}
            <pre dir="ltr" className="mt-1 overflow-x-auto bg-slate-50 p-1 text-xs">
              {JSON.stringify(r.config, null, 1)}
            </pre>
            {r.state === "proposed" && (
              <div className="mt-1 flex flex-wrap gap-2">
                <input aria-label="دلیل بررسی" value={reason} onChange={(e) => setReason(e.target.value)} className="field field-sm" placeholder="دلیل" />
                <button type="button" className="btn btn-success btn-sm" onClick={() => review.mutate({ id: r.id, approve: true })}>
                  تأیید و فعال‌سازی
                </button>
                <button type="button" className="btn btn-danger btn-sm" onClick={() => review.mutate({ id: r.id, approve: false })}>
                  رد
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <ErrorNotice error={review.error} />
      <Samples source={source} />
      <ProposeRule source={source} />
    </div>
  );
}

function Qualification({ source }: { source: Source }) {
  const [runId, setRunId] = useState<string | null>(null);
  const client = useQueryClient();
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/qualification-runs", { body: { source_ids: [source.id], sample_size: QUALIFICATION_SAMPLE }, headers: idempotencyKey() }),
        QualificationRunSchema,
      ),
    onSuccess: (run) => setRunId(run.id),
  });
  const run = useQuery({
    queryKey: ["qualification", runId],
    enabled: runId !== null,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/qualification-runs/{run_id}", { params: { path: { run_id: runId ?? "" } } }), QualificationRunSchema),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 3_000 : false),
  });
  const decide = useMutation({
    mutationFn: async (v: Record<string, string>) =>
      unwrap(
        await api.POST("/api/v1/qualification-runs/{run_id}/sources/{source_id}/decision", {
          params: { path: { run_id: runId ?? "", source_id: source.id } },
          body: { decision: v.decision === "approve" ? "approve" : "reject", reason: v.reason ?? "" },
          headers: idempotencyKey(),
        }),
        LooseObjectSchema,
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });
  return (
    <div className="flex flex-col gap-2">
      <h4 className="font-medium">ارزیابی کیفیت منبع</h4>
      <button type="button" onClick={() => start.mutate()} disabled={start.isPending} className="self-start btn btn-secondary">
        شروع ارزیابی
      </button>
      <ErrorNotice error={start.error ?? run.error} />
      {run.data && (
        <div className="text-sm">
          وضعیت: {run.data.status === "running" ? "در حال اجرا" : "کامل"}
          {run.data.report && (
            <pre dir="ltr" className="mt-1 max-h-48 overflow-auto bg-slate-50 p-1 text-xs">
              {JSON.stringify(run.data.report, null, 1)}
            </pre>
          )}
          {run.data.status === "completed" && (
            <form onSubmit={(e) => decide.mutate(form(e))} className="mt-2 flex flex-wrap items-end gap-2" aria-label="تصمیم ارزیابی">
              <label className="flex flex-col">
                تصمیم
                <select name="decision" className="field">
                  <option value="approve">تأیید منبع</option>
                  <option value="reject">رد منبع</option>
                </select>
              </label>
              <Field name="reason" label="دلیل" required />
              <button type="submit" className="btn btn-primary">
                ثبت
              </button>
              <ErrorNotice error={decide.error} />
              {decide.isSuccess && <SuccessNotice>تصمیم ارزیابی ثبت شد.</SuccessNotice>}
            </form>
          )}
        </div>
      )}
    </div>
  );
}

function CreateSource() {
  const client = useQueryClient();
  const [method, setMethod] = useState<Source["method"]>("html");
  const create = useMutation({
    mutationFn: async (v: Record<string, string>) =>
      unwrap(
        await api.POST("/api/v1/sources", {
          body: {
            name: v.name ?? "",
            base_domain: v.base_domain ?? "",
            connector_key: v.connector_key || "generic_html",
            method: (v.method ?? "html") as Source["method"],
            currency_unit: (v.currency_unit ?? "TOMAN") as Source["currency_unit"],
            quota_per_minute: Number(v.quota_per_minute ?? 10),
            interval_a_seconds: 900,
            interval_b_seconds: 3_600,
            interval_c_seconds: 21_600,
          },
          headers: idempotencyKey(),
        }),
        SourceSchema,
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });
  return (
    <form onSubmit={(e) => create.mutate(form(e))} className="flex flex-wrap items-end gap-2 card p-4" aria-label="منبع جدید" data-tour="sources-create">
      <Field name="name" label="نام" required />
      <Field name="base_domain" label="دامنه" required dir="ltr" />
      <label className="field-label">
        روش دریافت
        <select name="method" className="field" value={method} onChange={(e) => setMethod(e.target.value as Source["method"])}>
          {(Object.keys(METHOD_FA) as Source["method"][]).map((m) => (
            <option key={m} value={m}>
              {METHOD_FA[m]}
            </option>
          ))}
        </select>
      </label>
      <label className="field-label">
        کلید رابط
        <select name="connector_key" className="field" dir="ltr" key={method}>
          {connectorsFor(method).map((c) => (
            <option key={c.key} value={c.key}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      <label className="field-label">
        واحد پول
        <select name="currency_unit" className="field">
          <option value="TOMAN">تومان</option>
          <option value="RIAL">ریال</option>
        </select>
      </label>
      <Field name="quota_per_minute" label="سهمیه در دقیقه" type="number" min={1} defaultValue={10} />
      <button type="submit" className="btn btn-primary" disabled={create.isPending}>
        افزودن منبع
      </button>
      <ErrorNotice error={create.error} />
    </form>
  );
}

export function SourcesView() {
  const [selected, setSelected] = useState<string | null>(null);
  const sources = useQuery({
    queryKey: ["sources"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sources"), z.array(SourceSchema)),
  });
  const health = useQuery({
    queryKey: ["sources-health"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sources-health"), z.array(SourceHealthSchema)),
  });
  if (sources.isPending) return <Loading />;
  if (sources.error) return <ErrorNotice error={sources.error} />;
  const healthBySource = new Map((health.data ?? []).map((h) => [h.source_id, h]));
  const current = sources.data.find((s) => s.id === selected);
  return (
    <section className="page">
      <PageHeading
        title="منابع داده"
        subtitle="فقط منابع تأییدشده و دارای مجوز دسترسی در محاسبه قیمت استفاده می‌شوند."
        tour="sources"
      />
      <CreateSource />
      <table className="data-table data-table-compact" aria-label="منابع" data-tour="sources-table">
        <thead>
          <tr>
            <th>نام</th>
            <th>دامنه</th>
            <th>وضعیت</th>
            <th>موفقیت ۲۴ ساعت</th>
            <th>میانه قدمت داده</th>
            <th>مسدودشدن</th>
            <th>هزینه برآوردی</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {sources.data.map((s) => {
            const h = healthBySource.get(s.id);
            return (
              <tr key={s.id} className="border-t" data-source={s.id}>
                <td>{s.name}</td>
                <td>
                  <bdi dir="ltr">{s.base_domain}</bdi>
                </td>
                <td>{STATUS_FA[s.status]}</td>
                <td>{h?.success_rate !== null && h?.success_rate !== undefined ? percent(h.success_rate * 100) : "—"}</td>
                <td>{minutes(h?.data_age_median_seconds)}</td>
                <td>{h ? <FaNum value={h.blocked} /> : "—"}</td>
                <td>{h ? <Money rial={h.estimated_cost_rial} /> : "—"}</td>
                <td>
                  <button type="button" className="btn-ghost" onClick={() => setSelected(s.id)}>
                    مدیریت
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {current && (
        <section className="flex flex-col gap-4 card p-5" aria-label={`منبع ${current.name}`} data-tour="sources-detail">
          <h2 className="section-title">
            {current.name} — {STATUS_FA[current.status]}
          </h2>
          <EditSource key={`${current.id}-${current.status}`} source={current} />
          <hr className="border-slate-100" />
          <StatusChange source={current} />
          <hr className="border-slate-100" />
          <Clearances source={current} />
          <hr className="border-slate-100" />
          <ExtractionRules source={current} />
          <hr className="border-slate-100" />
          <Qualification source={current} />
          <hr className="border-slate-100" />
          <DeleteSource source={current} onDeleted={() => setSelected(null)} />
        </section>
      )}
    </section>
  );
}
