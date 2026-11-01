import type { ReactNode } from "react";
import { ApiError } from "@/lib/api/client";

const BOX = "flex items-start gap-3 rounded-xl border px-4 py-3 text-sm";

/** Decorative icon: an SVG, so it adds nothing to the notice's text or accessible name. */
function Icon({ d, className }: { d: string; className: string }) {
  return (
    <svg aria-hidden viewBox="0 0 20 20" fill="currentColor" className={`mt-0.5 size-4 shrink-0 ${className}`}>
      <path fillRule="evenodd" clipRule="evenodd" d={d} />
    </svg>
  );
}
const CHECK = "M16.7 5.3a1 1 0 010 1.4l-8 8a1 1 0 01-1.4 0l-4-4a1 1 0 111.4-1.4L8 12.6l7.3-7.3a1 1 0 011.4 0z";
const WARN =
  "M8.5 3.5a1.7 1.7 0 013 0l6 10.5A1.7 1.7 0 0116 16.5H4a1.7 1.7 0 01-1.5-2.5l6-10.5zM10 7a.8.8 0 00-.8.8v3a.8.8 0 001.6 0v-3A.8.8 0 0010 7zm0 7a1 1 0 100-2 1 1 0 000 2z";

export function SuccessNotice({ children }: { children: ReactNode }) {
  return (
    <div role="status" className={`${BOX} border-emerald-200 bg-emerald-50 text-emerald-900`}>
      <Icon d={CHECK} className="text-emerald-600" />
      <div>{children}</div>
    </div>
  );
}

export function WarningNotice({ children }: { children: ReactNode }) {
  return (
    <div role="status" className={`${BOX} border-amber-200 bg-amber-50 text-amber-950`}>
      <Icon d={WARN} className="text-amber-600" />
      <div>{children}</div>
    </div>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.messageFa : "خطایی رخ داد؛ دوباره تلاش کنید.";
  return (
    <div role="alert" className={`${BOX} border-rose-200 bg-rose-50 text-rose-900`}>
      {message}
    </div>
  );
}

export function Loading() {
  return (
    <p role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-slate-500">
      <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      در حال بارگذاری…
    </p>
  );
}
