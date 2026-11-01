"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { z } from "zod";
import { When } from "@/components/format";
import { ErrorNotice, Loading, SuccessNotice } from "@/components/notices";
import { useIsAdmin } from "@/components/viewer-context";
import { api, idempotencyKey, unwrap } from "@/lib/api/client";
import { SourceSchema, TrackedOfferSchema, type TrackedOffer } from "@/lib/api/schemas";

const STATUS_FA: Record<TrackedOffer["status"], string> = {
  active: "در حال پایش",
  paused: "متوقف",
  suggested: "پیشنهادی (در انتظار تأیید)",
  dismissed: "کنار گذاشته‌شده",
};
const STATUS_STYLE: Record<TrackedOffer["status"], string> = {
  active: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  paused: "bg-slate-100 text-slate-700 ring-slate-500/20",
  suggested: "bg-amber-50 text-amber-800 ring-amber-600/20",
  dismissed: "bg-slate-50 text-slate-600 ring-slate-500/20",
};

/** Pause or resume one offer (admin); a reason is recorded with the change. */
function PauseToggle({ offer, onDone }: { offer: TrackedOffer; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const paused = offer.status === "paused";
  const toggle = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tracked-offers/{tracked_offer_id}/pause", {
          params: { path: { tracked_offer_id: offer.id } },
          body: { paused: !paused, reason },
          headers: idempotencyKey(),
        }),
        TrackedOfferSchema,
      ),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      onDone();
    },
  });
  if (!open) {
    return (
      <button type="button" className="btn-ghost" onClick={() => setOpen(true)}>
        {paused ? "ادامه پایش" : "توقف پایش"}
      </button>
    );
  }
  return (
    <form
      className="flex flex-wrap items-center gap-1"
      onSubmit={(e) => {
        e.preventDefault();
        toggle.mutate();
      }}
    >
      <input aria-label="دلیل" placeholder="دلیل" required value={reason} onChange={(e) => setReason(e.target.value)} className="field field-sm w-40" />
      <button type="submit" className="btn btn-primary btn-sm" disabled={toggle.isPending}>
        ثبت
      </button>
      <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>
        انصراف
      </button>
      <ErrorNotice error={toggle.error} />
    </form>
  );
}

/** The competitor pages tracked for this product, and registering a new one. */
export function TrackedOffers({ variantId }: { variantId: string }) {
  const client = useQueryClient();
  const isAdmin = useIsAdmin();
  const offers = useQuery({
    queryKey: ["tracked-offers", variantId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/variants/{variant_id}/tracked-offers", { params: { path: { variant_id: variantId } } }),
        z.array(TrackedOfferSchema),
      ),
  });
  const sources = useQuery({
    queryKey: ["sources"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sources"), z.array(SourceSchema)),
  });
  const [sourceId, setSourceId] = useState("");
  const [url, setUrl] = useState("");
  const [own, setOwn] = useState<"" | "store" | "channel">("");
  const register = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tracked-offers", {
          body: {
            source_id: sourceId,
            variant_id: variantId,
            url: url.trim(),
            is_own_store: own === "store",
            is_own_channel: own === "channel",
          },
          headers: idempotencyKey(),
        }),
        TrackedOfferSchema,
      ),
    onSuccess: () => {
      setUrl("");
      setOwn("");
      void client.invalidateQueries({ queryKey: ["tracked-offers", variantId] });
    },
  });
  const refresh = () => void client.invalidateQueries({ queryKey: ["tracked-offers", variantId] });
  const byId = new Map((sources.data ?? []).map((s) => [s.id, s]));
  // the server accepts offers only on cleared sources that are under evaluation or approved
  const usable = (sources.data ?? []).filter((s) => s.status === "under_evaluation" || s.status === "approved");
  const visible = (offers.data ?? []).filter((o) => o.status !== "dismissed");

  return (
    <section className="flex flex-col gap-3" aria-labelledby="tracked-offers-title" data-tour="detail-offers">
      <h2 id="tracked-offers-title" className="section-title">
        آگهی‌های پایش‌شده
      </h2>
      {offers.isPending ? (
        <Loading />
      ) : offers.error ? (
        <ErrorNotice error={offers.error} />
      ) : visible.length === 0 ? (
        <p className="empty">هنوز نشانی آگهی‌ای برای این کالا ثبت نشده است؛ بدون آن قیمتی از بازار دریافت نمی‌شود.</p>
      ) : (
        <table className="data-table data-table-compact" aria-label="آگهی‌های پایش‌شده">
          <thead>
            <tr>
              <th>منبع</th>
              <th>نشانی</th>
              <th>وضعیت</th>
              <th>نوبت بعدی دریافت</th>
              <th>ثبت</th>
              {isAdmin && <th>اقدام</th>}
            </tr>
          </thead>
          <tbody>
            {visible.map((o) => (
              <tr key={o.id} data-offer={o.id}>
                <td>
                  {byId.get(o.source_id)?.name ?? "—"}
                  {o.is_own_store && <span className="ms-1 badge bg-brand-50 text-brand-700 ring-brand-500/25">فروشگاه ما</span>}
                  {o.is_own_channel && <span className="ms-1 badge bg-brand-50 text-brand-700 ring-brand-500/25">آگهی ما در کانال</span>}
                </td>
                <td className="max-w-72 truncate">
                  <a href={o.url} target="_blank" rel="noopener noreferrer" className="link" dir="ltr">
                    {o.url}
                  </a>
                </td>
                <td>
                  <span className={`badge ${STATUS_STYLE[o.status]}`}>{STATUS_FA[o.status]}</span>
                </td>
                <td>{o.status === "active" && o.next_due_at ? <When at={o.next_due_at} /> : "—"}</td>
                <td>
                  <bdi>{o.created_by}</bdi>
                </td>
                {isAdmin && (
                  <td>{o.status === "active" || o.status === "paused" ? <PauseToggle offer={o} onDone={refresh} /> : "—"}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form
        className="card flex flex-wrap items-end gap-3 p-4"
        aria-label="افزودن نشانی آگهی"
        onSubmit={(e) => {
          e.preventDefault();
          register.mutate();
        }}
      >
        <label className="field-label">
          منبع
          <select required value={sourceId} onChange={(e) => setSourceId(e.target.value)} className="field min-w-44">
            <option value="">انتخاب منبع</option>
            {usable.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.base_domain})
              </option>
            ))}
          </select>
        </label>
        <label className="field-label grow">
          نشانی صفحه کالا در منبع
          <input
            required
            dir="ltr"
            type="url"
            placeholder={sourceId ? `https://${byId.get(sourceId)?.base_domain ?? ""}/...` : "https://..."}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="field"
          />
        </label>
        {isAdmin && (
          <label className="field-label">
            نوع آگهی
            <select value={own} onChange={(e) => setOwn(e.target.value as typeof own)} className="field">
              <option value="">آگهی رقیب</option>
              <option value="store">صفحه کالا در فروشگاه ما</option>
              <option value="channel">آگهی ما در سایت مقایسه</option>
            </select>
          </label>
        )}
        <button type="submit" className="btn btn-primary" disabled={register.isPending}>
          افزودن نشانی
        </button>
        <p className="basis-full text-xs leading-5 text-slate-600">
          فقط منابع «در حال ارزیابی» یا «تأییدشده» که مجوز دسترسی دارند قابل انتخاب‌اند، و نشانی باید از دامنه همان منبع باشد.
        </p>
        {register.isSuccess && (
          <div className="basis-full">
            <SuccessNotice>نشانی ثبت شد و طبق برنامه سطح اهمیت کالا پایش می‌شود.</SuccessNotice>
          </div>
        )}
        <div className="basis-full">
          <ErrorNotice error={register.error ?? sources.error} />
        </div>
      </form>
    </section>
  );
}
