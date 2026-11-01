"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { z } from "zod";
import { When } from "@/components/format";
import { ErrorNotice, Loading, SuccessNotice } from "@/components/notices";
import { PageHeading } from "@/components/tour/help-button";
import { api, idempotencyKey, unwrap } from "@/lib/api/client";
import { LooseObjectSchema, RuleVersionSchema, type RuleVersion } from "@/lib/api/schemas";
import { faNumber, toman } from "@/lib/format";

/** Every rule field with the unit the admin types and its conversion to the API's unit. */
const FIELDS = [
  { key: "min_margin_bp", label: "حداقل حاشیه سود (٪)", unit: "percent" },
  { key: "fee_rate_bp", label: "کارمزد فروش (٪)", unit: "percent" },
  { key: "vat_rate_bp", label: "مالیات بر ارزش افزوده (٪)", unit: "percent" },
  { key: "undercut_step_rial", label: "فاصله زیر قیمت بازار (تومان)", unit: "toman" },
  { key: "hold_tolerance_bp", label: "دامنه تحمل بدون تغییر (٪)", unit: "percent" },
  { key: "rounding_step_rial", label: "گام گرد کردن (تومان)", unit: "toman" },
  { key: "ceiling_rial", label: "سقف قیمت (تومان، اختیاری)", unit: "toman" },
  { key: "max_data_age_a_seconds", label: "حداکثر قدمت داده — اهمیت الف (دقیقه)", unit: "minutes" },
  { key: "max_data_age_b_seconds", label: "حداکثر قدمت داده — اهمیت ب (دقیقه)", unit: "minutes" },
  { key: "max_data_age_c_seconds", label: "حداکثر قدمت داده — اهمیت ج (دقیقه)", unit: "minutes" },
  { key: "outlier_threshold_bp", label: "آستانه قیمت پرت زیر میانه (٪)", unit: "percent" },
  { key: "min_qualifying_offers", label: "حداقل تعداد پیشنهاد معتبر", unit: "count" },
] as const;
type FieldKey = (typeof FIELDS)[number]["key"];
type Unit = (typeof FIELDS)[number]["unit"];

export function toApi(unit: Unit, text: string): number | null {
  const value = Number(text.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[,٬\s]/g, ""));
  if (!text.trim() || !Number.isFinite(value)) return null;
  switch (unit) {
    case "percent":
      return Math.round(value * 100); // basis points
    case "toman":
      return Math.round(value * 10); // Rial
    case "minutes":
      return Math.round(value * 60); // seconds
    default:
      return Math.round(value);
  }
}

export function fromApi(unit: Unit, value: unknown): string {
  if (typeof value !== "number") return "";
  switch (unit) {
    case "percent":
      return String(value / 100);
    case "toman":
      return String(value / 10);
    case "minutes":
      return String(value / 60);
    default:
      return String(value);
  }
}

function display(unit: Unit, value: unknown): string {
  if (typeof value !== "number") return "—";
  if (unit === "toman") return toman(value);
  if (unit === "percent") return `${faNumber(value / 100, true)}٪`;
  if (unit === "minutes") return `${faNumber(value / 60, true)} دقیقه`;
  return faNumber(value);
}

function RuleForm({ initial, onSaved }: { initial: Record<string, unknown>; onSaved: () => void }) {
  const [scope, setScope] = useState<"default" | "category">("default");
  const [category, setCategory] = useState("");
  const [values, setValues] = useState<Record<FieldKey, string>>(
    () => Object.fromEntries(FIELDS.map((f) => [f.key, fromApi(f.unit, initial[f.key])])) as Record<FieldKey, string>,
  );
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        reason,
        ...Object.fromEntries(FIELDS.map((f) => [f.key, toApi(f.unit, values[f.key])])),
      };
      const result =
        scope === "default"
          ? await api.PUT("/api/v1/rules/default", { body: body as never, headers: idempotencyKey() })
          : await api.PUT("/api/v1/rules/category/{category}", {
              params: { path: { category } },
              body: body as never,
              headers: idempotencyKey(),
            });
      return unwrap(result, LooseObjectSchema);
    },
    onSuccess: onSaved,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }
  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-3 card p-5 md:grid-cols-3" aria-label="نسخه جدید قاعده" data-tour="rules-form">
      <label className="field-label">
        دامنه قاعده
        <select value={scope} onChange={(e) => setScope(e.target.value as "default" | "category")} className="field">
          <option value="default">پیش‌فرض</option>
          <option value="category">دسته کالا</option>
        </select>
      </label>
      {scope === "category" && (
        <label className="field-label">
          دسته
          <input required value={category} onChange={(e) => setCategory(e.target.value)} className="field" />
        </label>
      )}
      {FIELDS.map((f) => (
        <label key={f.key} className="field-label">
          {f.label}
          <input
            name={f.key}
            inputMode="decimal"
            value={values[f.key]}
            onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
            className="field"
          />
        </label>
      ))}
      <label className="field-label col-span-full">
        دلیل تغییر
        <input required name="reason" value={reason} onChange={(e) => setReason(e.target.value)} className="field" />
      </label>
      <div className="col-span-full flex flex-col gap-2">
        <ErrorNotice error={save.error} />
        {save.isSuccess && <SuccessNotice>نسخه جدید قاعده ثبت شد.</SuccessNotice>}
        <button type="submit" disabled={save.isPending} className="self-start btn btn-primary">
          ثبت نسخه جدید
        </button>
      </div>
    </form>
  );
}

function VersionTable({ versions, label = "نسخه‌های جاری" }: { versions: RuleVersion[]; label?: string }) {
  return (
    <div className="overflow-x-auto" data-tour="rules-current">
      <table className="data-table data-table-compact text-xs" aria-label={label}>
        <thead>
          <tr>
            <th>دامنه</th>
            <th>نسخه</th>
            {FIELDS.map((f) => (
              <th key={f.key}>
                {f.label}
              </th>
            ))}
            <th>ثبت</th>
            <th>دلیل</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id} className="border-t">
              <td>{v.scope === "default" ? "پیش‌فرض" : `${v.scope}: ${v.scope_key ?? ""}`}</td>
              <td>{faNumber(v.version)}</td>
              {FIELDS.map((f) => (
                <td key={f.key} className="p-1">
                  {display(f.unit, (v as Record<string, unknown>)[f.key])}
                </td>
              ))}
              <td>
                <bdi>{v.created_by}</bdi> — <When at={v.created_at} />
              </td>
              <td className="min-w-40">{v.reason ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Every version of one rule scope, newest first; earlier versions are never changed. */
function RuleHistory() {
  const [scope, setScope] = useState<"default" | "category">("default");
  const [key, setKey] = useState("");
  const [submitted, setSubmitted] = useState<{ scope: "default" | "category"; key: string }>({ scope: "default", key: "" });
  const history = useQuery({
    queryKey: ["rule-history", submitted.scope, submitted.key],
    enabled: submitted.scope === "default" || submitted.key !== "",
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/rules/history", {
          params: { query: { scope: submitted.scope, key: submitted.scope === "category" ? submitted.key : undefined } },
        }),
        z.array(RuleVersionSchema),
      ),
  });
  return (
    <section className="flex flex-col gap-3" aria-labelledby="rule-history-title" data-tour="rules-history">
      <h2 id="rule-history-title" className="section-title">
        تاریخچه نسخه‌ها
      </h2>
      <form
        className="card flex flex-wrap items-end gap-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted({ scope, key: key.trim() });
        }}
      >
        <label className="field-label">
          دامنه قاعده
          <select value={scope} onChange={(e) => setScope(e.target.value as "default" | "category")} className="field">
            <option value="default">پیش‌فرض</option>
            <option value="category">دسته کالا</option>
          </select>
        </label>
        {scope === "category" && (
          <label className="field-label">
            دسته
            <input required value={key} onChange={(e) => setKey(e.target.value)} className="field" />
          </label>
        )}
        <button type="submit" className="btn btn-secondary">
          نمایش تاریخچه
        </button>
      </form>
      {history.isPending && history.fetchStatus !== "idle" ? (
        <Loading />
      ) : history.error ? (
        <ErrorNotice error={history.error} />
      ) : history.data && history.data.length > 0 ? (
        <VersionTable versions={[...(history.data as RuleVersion[])].sort((a, b) => b.version - a.version)} label="تاریخچه نسخه‌های قاعده" />
      ) : history.data ? (
        <p className="empty">برای این دامنه نسخه‌ای ثبت نشده است.</p>
      ) : null}
    </section>
  );
}

export function RulesView() {
  const client = useQueryClient();
  const current = useQuery({
    queryKey: ["rules"],
    queryFn: async () => unwrap(await api.GET("/api/v1/rules"), z.array(RuleVersionSchema)),
  });
  const defaults = useQuery({
    queryKey: ["rule-defaults"],
    queryFn: async () => unwrap(await api.GET("/api/v1/rules/suggested-defaults"), LooseObjectSchema),
  });
  if (current.isPending || defaults.isPending) return <Loading />;
  if (current.error || defaults.error) return <ErrorNotice error={current.error ?? defaults.error} />;
  const base = current.data.find((v) => v.scope === "default") ?? defaults.data;
  return (
    <section className="page">
      <PageHeading
        title="قواعد سود"
        subtitle="هر تغییر یک نسخه تازه است و نسخه‌های قبلی حفظ می‌شوند. کف قیمت = بهای تمام‌شده ÷ (۱ − حاشیه − کارمزد) × (۱ + مالیات)."
        tour="rules"
      />
      <VersionTable versions={current.data as RuleVersion[]} />
      <RuleForm
        initial={base as Record<string, unknown>}
        onSaved={() => {
          void client.invalidateQueries({ queryKey: ["rules"] });
          void client.invalidateQueries({ queryKey: ["rule-history"] });
        }}
      />
      <RuleHistory />
    </section>
  );
}
