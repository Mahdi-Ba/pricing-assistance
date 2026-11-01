"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ErrorNotice, Loading, SuccessNotice } from "@/components/notices";
import { PageHeading } from "@/components/tour/help-button";
import { api, idempotencyKey, unwrap } from "@/lib/api/client";
import { TenantSettingsSchema, type TenantSettings } from "@/lib/api/schemas";

type Values = Record<
  | "verification_window_minutes"
  | "recheck_daily_budget_per_user"
  | "evidence_retention_days"
  | "observation_retention_days"
  | "tier_a_coverage_pct"
  | "tier_a_data_age_p90_minutes"
  | "verification_reliability_pct"
  | "source_success_rate_pct",
  string
>;

function toValues(s: TenantSettings): Values {
  const text = (n: number | null) => (n === null ? "" : String(n));
  return {
    verification_window_minutes: text(s.verification_window_minutes),
    recheck_daily_budget_per_user: text(s.recheck_daily_budget_per_user),
    evidence_retention_days: text(s.evidence_retention_days),
    observation_retention_days: text(s.observation_retention_days),
    tier_a_coverage_pct: text(s.kpi_targets.tier_a_coverage_pct),
    tier_a_data_age_p90_minutes: text(s.kpi_targets.tier_a_data_age_p90_minutes),
    verification_reliability_pct: text(s.kpi_targets.verification_reliability_pct),
    source_success_rate_pct: text(s.kpi_targets.source_success_rate_pct),
  };
}

const optional = (v: string) => (v.trim() === "" ? null : Number(v));

function Setting({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <label className="field-label">
      {label}
      {children}
      <span className="text-xs leading-5 font-normal text-slate-600">{hint}</span>
    </label>
  );
}

function SettingsForm({ initial }: { initial: TenantSettings }) {
  const client = useQueryClient();
  const [v, setV] = useState<Values>(() => toValues(initial));
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/settings", {
          body: {
            verification_window_minutes: Number(v.verification_window_minutes),
            recheck_daily_budget_per_user: Number(v.recheck_daily_budget_per_user),
            evidence_retention_days: Number(v.evidence_retention_days),
            observation_retention_days: optional(v.observation_retention_days),
            kpi_targets: {
              tier_a_coverage_pct: optional(v.tier_a_coverage_pct),
              tier_a_data_age_p90_minutes: optional(v.tier_a_data_age_p90_minutes),
              verification_reliability_pct: optional(v.verification_reliability_pct),
              source_success_rate_pct: optional(v.source_success_rate_pct),
            },
          },
          headers: idempotencyKey(),
        }),
        TenantSettingsSchema,
      ),
    onSuccess: (saved) => {
      client.setQueryData(["settings"], saved);
      setV(toValues(saved));
    },
  });
  const input = (key: keyof Values, props: { min?: number; max?: number; required?: boolean; step?: string } = {}) => (
    <input
      type="number"
      inputMode="decimal"
      className="field w-48"
      value={v[key]}
      onChange={(e) => setV({ ...v, [key]: e.target.value })}
      required={props.required ?? true}
      min={props.min}
      max={props.max}
      step={props.step ?? "1"}
    />
  );
  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      aria-label="تنظیمات"
    >
      <section className="card flex flex-col gap-4 p-5" aria-labelledby="settings-work" data-tour="settings-work">
        <h2 id="settings-work" className="section-title">
          کار روزانه
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Setting
            label="مهلت مشاهده قیمت روی سایت (دقیقه)"
            hint="اگر قیمت جدید در این مدت پس از «انجام شد» روی سایت دیده نشود، کالا با وضعیت «مشاهده روی سایت دیر شده» به صف برمی‌گردد. پیش‌فرض ۱۲۰."
          >
            {input("verification_window_minutes", { min: 5, max: 10080 })}
          </Setting>
          <Setting
            label="سهمیه روزانه «بررسی دوباره» برای هر کاربر"
            hint="حداکثر تعداد دریافت فوری که هر کارشناس در روز می‌تواند درخواست کند (صفر = غیرفعال). پیش‌فرض ۵۰."
          >
            {input("recheck_daily_budget_per_user", { min: 0, max: 1000 })}
          </Setting>
        </div>
      </section>

      <section className="card flex flex-col gap-4 p-5" aria-labelledby="settings-retention" data-tour="settings-retention">
        <h2 id="settings-retention" className="section-title">
          نگهداری داده
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Setting label="نگهداری تصویر صفحه‌ها (روز)" hint="نسخه ذخیره‌شده صفحه‌های رقبا پس از این مدت حذف می‌شود. پیش‌فرض ۹۰.">
            {input("evidence_retention_days", { min: 1, max: 3650 })}
          </Setting>
          <Setting
            label="نگهداری سابقه قیمت‌ها (روز، اختیاری)"
            hint="خالی یعنی سابقه قیمت‌ها همیشه نگه داشته می‌شود. حداقل ۳۰ روز. حذف با کار زمان‌بندی‌شده و ثبت در سابقه ممیزی انجام می‌شود."
          >
            {input("observation_retention_days", { min: 30, max: 36500, required: false })}
          </Setting>
        </div>
      </section>

      <section className="card flex flex-col gap-4 p-5" aria-labelledby="settings-kpi" data-tour="settings-kpi">
        <h2 id="settings-kpi" className="section-title">
          هدف‌های گزارش هفتگی
        </h2>
        <p className="muted">خالی یعنی «هدف تعیین نشده». این هدف‌ها فقط در گزارش کنار مقدار اندازه‌گیری‌شده نمایش داده می‌شوند.</p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Setting label="پوشش کالاهای اهمیت الف (٪)" hint="سهم کالاهای «الف» که دست‌کم یک قیمت معتبر و تازه دارند.">
            {input("tier_a_coverage_pct", { min: 0, max: 100, required: false, step: "0.1" })}
          </Setting>
          <Setting label="قدمت داده اهمیت الف، صدک ۹۰ (دقیقه)" hint="۹۰٪ داده‌های کالاهای «الف» باید از این تازه‌تر باشند.">
            {input("tier_a_data_age_p90_minutes", { min: 1, required: false })}
          </Setting>
          <Setting label="اطمینان مشاهده روی سایت در مهلت (٪)" hint="سهم تصمیم‌های «انجام شد» که در مهلت روی سایت دیده شده‌اند.">
            {input("verification_reliability_pct", { min: 0, max: 100, required: false, step: "0.1" })}
          </Setting>
          <Setting label="نرخ موفقیت دریافت از منابع (٪)" hint="سهم درخواست‌های موفق به همه منابع.">
            {input("source_success_rate_pct", { min: 0, max: 100, required: false, step: "0.1" })}
          </Setting>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className="btn btn-primary" disabled={save.isPending}>
          ذخیره تنظیمات
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => setV(toValues(initial))}>
          بازگرداندن تغییرات
        </button>
      </div>
      {save.isSuccess && <SuccessNotice>تنظیمات ذخیره شد و در سابقه ممیزی ثبت شد.</SuccessNotice>}
      <ErrorNotice error={save.error} />
    </form>
  );
}

export function SettingsView() {
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/settings"), TenantSettingsSchema),
  });
  return (
    <section className="page">
      <PageHeading title="تنظیمات" subtitle="تنظیمات عملیاتی این فروشگاه. هر تغییر با نام شما در سابقه ممیزی ثبت می‌شود." tour="settings" />
      {settings.isPending ? <Loading /> : settings.error ? <ErrorNotice error={settings.error} /> : <SettingsForm initial={settings.data} />}
    </section>
  );
}
