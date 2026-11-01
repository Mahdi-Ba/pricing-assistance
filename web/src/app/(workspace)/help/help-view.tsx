"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { TOURS, type TourId } from "@/components/tour/tour-content";
import { useIsAdmin } from "@/components/viewer-context";
import { faNumber } from "@/lib/format";
import { GLOSSARY, PRINCIPLES, WORKFLOW } from "./help-content";

/** Where each tour runs; the item tour needs an item, so it starts from the item page itself. */
const TOUR_PATH: Record<TourId, string | null> = {
  queue: "/queue",
  detail: null,
  matches: "/matches",
  reports: "/reports",
  imports: "/catalog/imports",
  rules: "/rules",
  sources: "/sources",
  settings: "/settings",
};

export function HelpView() {
  const router = useRouter();
  const isAdmin = useIsAdmin();
  const tours = Object.values(TOURS).filter((t) => isAdmin || !t.adminOnly);
  return (
    <section className="page">
      <header className="page-header">
        <h1 className="page-title">راهنما</h1>
        <p className="page-subtitle">این پنل چطور کار می‌کند، هر بخش چه معنایی دارد و پشت صحنه چه اتفاقی می‌افتد.</p>
      </header>

      <section className="flex flex-col gap-3" aria-labelledby="help-tours">
        <h2 id="help-tours" className="section-title">
          راهنمای تعاملی صفحه‌ها
        </h2>
        <p className="muted">هر راهنما روی همان صفحه اجرا می‌شود و بخش‌ها را یکی‌یکی نشان می‌دهد.</p>
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {tours.map((t) => {
            const path = TOUR_PATH[t.id];
            const steps = t.steps.filter((s) => isAdmin || !s.adminOnly).length;
            return (
              <li key={t.id} className="card flex flex-col gap-3 p-5">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-semibold text-slate-900">{t.title}</h3>
                  <span className="badge bg-slate-50 text-slate-700 ring-slate-500/20">{faNumber(steps)} گام</span>
                </div>
                <p className="flex-1 text-sm leading-6 text-slate-600">{t.summary}</p>
                {path ? (
                  <button type="button" className="btn btn-primary btn-sm self-start" onClick={() => router.push(`${path}?tour=${t.id}`)}>
                    شروع راهنما
                  </button>
                ) : (
                  <p className="text-xs leading-5 text-slate-600">
                    از <Link href="/queue" className="link">صف بررسی</Link> یک کالا را باز کنید و «راهنمای این صفحه» را بزنید.
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <section className="card flex flex-col gap-4 p-5" aria-labelledby="help-flow">
        <h2 id="help-flow" className="section-title">
          چرخه کار در یک نگاه
        </h2>
        <ol className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {WORKFLOW.map((s, i) => (
            <li key={s.title} className="flex gap-3">
              <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-full bg-brand-50 text-sm font-bold text-brand-700">
                {faNumber(i + 1)}
              </span>
              <div className="text-sm leading-6">
                <span className="font-semibold text-slate-900">{s.title}</span>
                {s.admin && <span className="ms-2 badge bg-violet-50 text-violet-700 ring-violet-600/20">مدیر</span>}
                <p className="text-slate-600">{s.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="flex flex-col gap-3" aria-labelledby="help-glossary">
        <h2 id="help-glossary" className="section-title">
          واژه‌نامه
        </h2>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {GLOSSARY.map((g) => (
            <section key={g.group} className="card flex flex-col gap-3 p-5" aria-label={g.group}>
              <h3 className="font-semibold text-brand-700">{g.group}</h3>
              <dl className="flex flex-col divide-y divide-slate-100">
                {g.terms.map((t) => (
                  <div key={t.term} className="py-2.5 first:pt-0 last:pb-0">
                    <dt className="text-sm font-semibold text-slate-900">{t.term}</dt>
                    <dd className="mt-0.5 text-sm leading-6 text-slate-600">{t.text}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </section>

      <section className="card flex flex-col gap-3 border-emerald-200 bg-emerald-50/50 p-5" aria-labelledby="help-principles">
        <h2 id="help-principles" className="section-title">
          اصول ایمنی سامانه
        </h2>
        <ul className="flex list-disc flex-col gap-1.5 ps-5 text-sm leading-6 text-slate-700 marker:text-emerald-600">
          {PRINCIPLES.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </section>
    </section>
  );
}
