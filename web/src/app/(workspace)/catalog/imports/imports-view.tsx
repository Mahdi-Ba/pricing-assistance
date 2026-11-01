"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { FaNum, Money, When } from "@/components/format";
import { ErrorNotice, Loading, SuccessNotice } from "@/components/notices";
import { PageHeading } from "@/components/tour/help-button";
import { api, idempotencyKey, toApiError, unwrap } from "@/lib/api/client";
import { CostComponentSchema, CostRecordSchema, ImportReportSchema, type ImportReport } from "@/lib/api/schemas";
import { z } from "zod";
import { faNumber, parseTomanToRial } from "@/lib/format";

function Report({ report }: { report: ImportReport }) {
  return (
    <section className="flex flex-col gap-2 card p-4" aria-label="گزارش ورود">
      <h3 className="section-title">
        گزارش «<bdi>{report.file_name}</bdi>»
      </h3>
      <p className="text-sm">
        کل <FaNum value={report.rows_total} /> · جدید <FaNum value={report.rows_created} /> · به‌روزشده{" "}
        <FaNum value={report.rows_updated} /> · بدون تغییر <FaNum value={report.rows_unchanged} /> · رد{" "}
        <FaNum value={report.rows_rejected} /> · در انتظار تأیید <FaNum value={report.rows_held} />
      </p>
      {report.errors.length > 0 && (
        <table className="data-table data-table-compact" aria-label="خطاهای ردیف‌ها">
          <thead>
            <tr>
              <th>ردیف</th>
              <th>ستون</th>
              <th>خطا</th>
            </tr>
          </thead>
          <tbody>
            {report.errors.map((e, i) => (
              <tr key={i} className="border-t">
                <td>{e.row !== null ? <FaNum value={e.row} /> : "—"}</td>
                <td>
                  <bdi>{e.column ?? "—"}</bdi>
                </td>
                <td>{e.message_fa}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function HeldCosts() {
  const client = useQueryClient();
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const held = useQuery({
    queryKey: ["held-costs"],
    queryFn: async () => unwrap(await api.GET("/api/v1/catalog/held-costs"), z.array(CostRecordSchema)),
  });
  const review = useMutation({
    mutationFn: async ({ id, confirm }: { id: string; confirm: boolean }) =>
      unwrap(
        await api.POST("/api/v1/catalog/costs/{cost_record_id}/review", {
          params: { path: { cost_record_id: id } },
          body: { decision: confirm ? "confirm" : "reject", reason: reasons[id] ?? "" },
          headers: idempotencyKey(),
        }),
        CostRecordSchema,
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["held-costs"] }),
  });
  if (held.isPending) return <Loading />;
  if (held.error) return <ErrorNotice error={held.error} />;
  if (!held.data.length) return <p className="text-slate-600">هزینه‌ای در انتظار تأیید نیست.</p>;
  return (
    <table className="data-table data-table-compact" aria-label="هزینه‌های مشکوک به خطای واحد">
      <thead>
        <tr>
          <th>کالا</th>
          <th>هزینه جدید</th>
          <th>هزینه قبلی</th>
          <th>دلیل</th>
          <th>اقدام</th>
        </tr>
      </thead>
      <tbody>
        {held.data.map((c) => (
          <tr key={c.id} className="border-t" data-cost={c.id}>
            <td className="text-xs">
              <bdi>{c.variant_id}</bdi>
            </td>
            <td>
              <Money rial={c.purchase_cost_rial} />
            </td>
            <td>
              <Money rial={c.previous_cost_rial} />
            </td>
            <td>
              <input
                aria-label="دلیل"
                value={reasons[c.id] ?? ""}
                onChange={(e) => setReasons({ ...reasons, [c.id]: e.target.value })}
                className="field field-sm"
              />
            </td>
            <td className="flex gap-1">
              <button type="button" className="btn btn-success btn-sm" onClick={() => review.mutate({ id: c.id, confirm: true })}>
                تأیید
              </button>
              <button type="button" className="btn btn-danger btn-sm" onClick={() => review.mutate({ id: c.id, confirm: false })}>
                رد
              </button>
            </td>
          </tr>
        ))}
        <tr>
          <td colSpan={5}>
            <ErrorNotice error={review.error} />
          </td>
        </tr>
      </tbody>
    </table>
  );
}

async function downloadTemplate() {
  const response = await fetch("/api/backend/api/v1/catalog/import-template");
  if (!response.ok) return;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "catalog-template.csv";
  link.click();
  URL.revokeObjectURL(url);
}

/** Fixed per-unit costs added to every purchase cost (all products, or one category). */
function CostComponents() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [closing, setClosing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const list = useQuery({
    queryKey: ["cost-components"],
    queryFn: async () => unwrap(await api.GET("/api/v1/catalog/cost-components"), z.array(CostComponentSchema)),
  });
  const add = useMutation({
    mutationFn: async () => {
      const rial = parseTomanToRial(amount);
      if (rial === null) throw new Error("amount");
      return unwrap(
        await api.POST("/api/v1/catalog/cost-components", {
          body: { name: name.trim(), amount_rial: rial, category: category.trim() || null },
          headers: idempotencyKey(),
        }),
        CostComponentSchema,
      );
    },
    onSuccess: () => {
      setName("");
      setAmount("");
      setCategory("");
      void client.invalidateQueries({ queryKey: ["cost-components"] });
    },
  });
  const deactivate = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/catalog/cost-components/{component_id}/deactivate", {
          params: { path: { component_id: id } },
          body: { reason },
          headers: idempotencyKey(),
        }),
        CostComponentSchema,
      ),
    onSuccess: () => {
      setClosing(null);
      setReason("");
      void client.invalidateQueries({ queryKey: ["cost-components"] });
    },
  });
  const active = (list.data ?? []).filter((c) => c.active);
  const inactive = (list.data ?? []).filter((c) => !c.active);
  return (
    <section className="flex flex-col gap-3" aria-labelledby="cost-components-title" data-tour="imports-components">
      <h2 id="cost-components-title" className="section-title">
        اجزای ثابت بهای تمام‌شده
      </h2>
      <p className="muted">
        هزینه‌های ثابت هر عدد کالا (حمل، بیمه، ترخیص، انبار، بسته‌بندی و…) که به هزینه خرید اضافه می‌شوند و کف سود را تغییر می‌دهند.
      </p>
      {list.isPending ? (
        <Loading />
      ) : list.error ? (
        <ErrorNotice error={list.error} />
      ) : active.length === 0 ? (
        <p className="empty">جزء فعالی ثبت نشده است؛ بهای تمام‌شده فقط هزینه خرید است.</p>
      ) : (
        <table className="data-table data-table-compact" aria-label="اجزای فعال بهای تمام‌شده">
          <thead>
            <tr>
              <th>نام</th>
              <th>مبلغ هر عدد</th>
              <th>دامنه</th>
              <th>ثبت</th>
              <th>اقدام</th>
            </tr>
          </thead>
          <tbody>
            {active.map((c) => (
              <tr key={c.id} data-component={c.id}>
                <td>{c.name}</td>
                <td>
                  <Money rial={c.amount_rial} />
                </td>
                <td>{c.category ?? "همه کالاها"}</td>
                <td>
                  <bdi>{c.created_by}</bdi> — <When at={c.created_at} />
                </td>
                <td>
                  {closing === c.id ? (
                    <form
                      className="flex flex-wrap items-center gap-1"
                      onSubmit={(e) => {
                        e.preventDefault();
                        deactivate.mutate(c.id);
                      }}
                    >
                      <input aria-label="دلیل غیرفعال کردن" placeholder="دلیل" required value={reason} onChange={(e) => setReason(e.target.value)} className="field field-sm w-40" />
                      <button type="submit" className="btn btn-danger btn-sm" disabled={deactivate.isPending}>
                        غیرفعال شود
                      </button>
                      <button type="button" className="btn-ghost" onClick={() => setClosing(null)}>
                        انصراف
                      </button>
                    </form>
                  ) : (
                    <button type="button" className="btn-ghost" onClick={() => setClosing(c.id)}>
                      غیرفعال کردن
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ErrorNotice error={deactivate.error} />
      <form
        className="card flex flex-wrap items-end gap-3 p-4"
        aria-label="افزودن جزء هزینه"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <label className="field-label">
          نام هزینه
          <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="مثلاً حمل" className="field" />
        </label>
        <label className="field-label">
          مبلغ هر عدد (تومان)
          <input required inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} className="field w-40" />
        </label>
        <label className="field-label">
          دسته (خالی = همه کالاها)
          <input value={category} onChange={(e) => setCategory(e.target.value)} className="field" />
        </label>
        <button type="submit" className="btn btn-primary" disabled={add.isPending}>
          افزودن جزء
        </button>
        <p className="basis-full text-xs leading-5 text-slate-600">
          اجزا ویرایش نمی‌شوند؛ برای تغییر مبلغ، جزء تازه بسازید و جزء قبلی را غیرفعال کنید. هر تغییر پیشنهاد قیمت کالاهای مشمول را دوباره محاسبه می‌کند.
        </p>
        {add.error && (
          <div className="basis-full">
            {add.error instanceof Error && add.error.message === "amount" ? (
              <p role="alert" className="text-sm text-rose-700">
                مبلغ را به تومان و به صورت عدد وارد کنید.
              </p>
            ) : (
              <ErrorNotice error={add.error} />
            )}
          </div>
        )}
      </form>
      {inactive.length > 0 && (
        <details className="text-sm text-slate-600">
          <summary className="cursor-pointer">اجزای غیرفعال‌شده ({faNumber(inactive.length)})</summary>
          <ul className="mt-2 flex flex-col gap-1">
            {inactive.map((c) => (
              <li key={c.id}>
                {c.name} — <Money rial={c.amount_rial} /> — {c.category ?? "همه کالاها"} — غیرفعال توسط <bdi>{c.deactivated_by}</bdi>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export function ImportsView() {
  const client = useQueryClient();
  const [report, setReport] = useState<ImportReport | null>(null);
  const imports = useQuery({
    queryKey: ["imports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/catalog/imports"), z.array(ImportReportSchema)),
  });
  const upload = useMutation({
    mutationFn: async (form: FormData) => {
      // multipart upload through the BFF; the browser sets the boundary
      const response = await fetch("/api/backend/api/v1/catalog/imports", {
        method: "POST",
        body: form,
        headers: idempotencyKey(),
      });
      const body: unknown = await response.json();
      if (!response.ok) throw toApiError(response.status, body);
      return ImportReportSchema.parse(body);
    },
    onSuccess: (data) => {
      setReport(data);
      void client.invalidateQueries({ queryKey: ["imports"] });
      void client.invalidateQueries({ queryKey: ["held-costs"] });
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    upload.mutate(new FormData(event.currentTarget));
  }
  return (
    <section className="page">
      <PageHeading
        title="ورود کاتالوگ"
        subtitle="کالاها، هزینه خرید، قیمت فعلی و سطح اهمیت را از فایل وارد کنید."
        tour="imports"
      />
      <form onSubmit={submit} className="card flex flex-wrap items-end gap-3 p-4" aria-label="بارگذاری فایل کاتالوگ" data-tour="imports-upload">
        <label className="field-label">
          فایل (CSV یا XLSX)
          <input type="file" name="file" required accept=".csv,.xlsx" className="field file:me-3 file:rounded-md file:border-0 file:bg-brand-50 file:px-3 file:py-1 file:text-brand-700" />
        </label>
        <label className="field-label">
          واحد پول پیش‌فرض
          <select name="default_currency" className="field">
            <option value="TOMAN">تومان</option>
            <option value="RIAL">ریال</option>
          </select>
        </label>
        <button type="submit" disabled={upload.isPending} className="btn btn-primary">
          بارگذاری
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => void downloadTemplate()}
        >
          دریافت قالب
        </button>
      </form>
      <ErrorNotice error={upload.error} />
      {report && (
        <>
          <SuccessNotice>فایل پردازش شد.</SuccessNotice>
          <Report report={report} />
        </>
      )}
      <CostComponents />
      <div className="flex flex-col gap-3" data-tour="imports-held">
        <h2 className="section-title">هزینه‌های در انتظار تأیید (احتمال خطای واحد)</h2>
        <HeldCosts />
      </div>
      <div className="flex flex-col gap-3" data-tour="imports-recent">
      <h2 className="section-title">ورودهای اخیر</h2>
      {imports.isPending ? (
        <Loading />
      ) : imports.error ? (
        <ErrorNotice error={imports.error} />
      ) : (
        <ul className="card flex flex-col divide-y divide-slate-100 text-sm">
          {imports.data.map((i) => (
            <li key={i.id} className="px-4 py-2.5">
              <bdi>{i.file_name}</bdi> — <When at={i.created_at} /> — رد <FaNum value={i.rows_rejected} />، در انتظار{" "}
              <FaNum value={i.rows_held} />
            </li>
          ))}
        </ul>
      )}
      </div>
    </section>
  );
}
