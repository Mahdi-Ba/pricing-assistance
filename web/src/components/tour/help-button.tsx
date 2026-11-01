"use client";

import type { TourId } from "./tour-content";
import { useTour } from "./tour-provider";

/** Starts the guided tour of the current page. */
export function HelpButton({ tour }: { tour: TourId }) {
  const { start } = useTour();
  return (
    <button type="button" className="btn btn-secondary btn-sm shrink-0" onClick={() => start(tour)} data-tour="help-button">
      <svg aria-hidden viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} className="size-4">
        <circle cx="10" cy="10" r="7.5" />
        <path d="M8 7.8a2 2 0 113 1.7c-.6.4-1 .8-1 1.5v.3" strokeLinecap="round" />
        <circle cx="10" cy="13.8" r=".6" fill="currentColor" />
      </svg>
      راهنمای این صفحه
    </button>
  );
}

/** Page title row: heading and optional subtitle, with the page's tour button opposite. */
export function PageHeading({ title, subtitle, tour }: { title: string; subtitle?: string; tour: TourId }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="page-header">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      <HelpButton tour={tour} />
    </header>
  );
}
