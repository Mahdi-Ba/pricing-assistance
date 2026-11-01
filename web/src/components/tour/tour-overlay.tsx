"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { faNumber } from "@/lib/format";
import type { TourStep } from "./tour-content";

type Rect = { top: number; left: number; width: number; height: number };

const GAP = 12; // between target and popover
const MARGIN = 16; // from the viewport edge
const PAD = 6; // spotlight padding around the target
const COMPACT = 640; // below this width the dialog is a bottom sheet

function sameRect(a: Rect | null, b: Rect | null): boolean {
  if (!a || !b) return a === b;
  return Math.abs(a.top - b.top) < 0.5 && Math.abs(a.left - b.left) < 0.5 && Math.abs(a.width - b.width) < 0.5 && Math.abs(a.height - b.height) < 0.5;
}

function findTarget(name: string | undefined): HTMLElement | null {
  if (!name) return null;
  const el = document.querySelector<HTMLElement>(`[data-tour="${CSS.escape(name)}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 ? el : null;
}

/**
 * The visible part of a guided tour: a spotlight around the step's target and a dialog with the
 * explanation. It follows the target while the page scrolls, resizes or loads data. A missing
 * target (not rendered for this user or this data) shows the step centred instead.
 */
export function TourOverlay({
  tourTitle,
  steps,
  index,
  onIndex,
  onClose,
}: {
  tourTitle: string;
  steps: TourStep[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
}) {
  const step = steps[index]!;
  const last = index === steps.length - 1;
  const dialog = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const [size, setSize] = useState({ width: 400, height: 320 });
  const [viewport, setViewport] = useState({ width: 1024, height: 768 });
  const titleId = useId();
  const bodyId = useId();

  // bring the target into view when the step changes
  useEffect(() => {
    const el = findTarget(step.target);
    if (!el) return;
    // phones show the step as a bottom sheet, so the target goes to the top of the screen
    const top = window.innerWidth < COMPACT || el.getBoundingClientRect().height > window.innerHeight * 0.6;
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ block: top ? "start" : "center", behavior: smooth ? "smooth" : "auto" });
  }, [step.target, index]);

  // track the target every frame (scrolling, resizing, data arriving, layout shifts)
  useEffect(() => {
    let frame = 0;
    let previous: Rect | null = null;
    const tick = () => {
      const el = findTarget(step.target);
      const r = el?.getBoundingClientRect();
      const next = r ? { top: r.top, left: r.left, width: r.width, height: r.height } : null;
      if (!sameRect(previous, next)) {
        previous = next;
        setRect(next);
      }
      setViewport((v) => (v.width === window.innerWidth && v.height === window.innerHeight ? v : { width: window.innerWidth, height: window.innerHeight }));
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [step.target]);

  useLayoutEffect(() => {
    const box = dialog.current?.getBoundingClientRect();
    if (box) setSize((s) => (Math.abs(s.width - box.width) < 1 && Math.abs(s.height - box.height) < 1 ? s : { width: box.width, height: box.height }));
  }, [index, rect]);

  // focus moves into the dialog so screen readers announce the step; restored on close
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    return () => before?.focus?.();
  }, []);
  useEffect(() => {
    dialog.current?.focus();
  }, [index]);

  function onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    } else if (event.key === "ArrowLeft" && !last) {
      event.preventDefault(); // RTL: left is forward
      onIndex(index + 1);
    } else if (event.key === "ArrowRight" && index > 0) {
      event.preventDefault();
      onIndex(index - 1);
    } else if (event.key === "Tab") {
      // keep keyboard focus inside the dialog while the tour is open
      const focusable = dialog.current?.querySelectorAll<HTMLElement>("button");
      if (!focusable?.length) return;
      const first = focusable[0]!;
      const end = focusable[focusable.length - 1]!;
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
        event.preventDefault();
        end.focus();
      } else if (!event.shiftKey && document.activeElement === end) {
        event.preventDefault();
        first.focus();
      }
    }
  }

  // placement: phones get a bottom sheet; otherwise below the target, else above, else beside it,
  // else pinned to the bottom. Right-aligned with the target (RTL).
  const compact = viewport.width < COMPACT;
  const width = Math.min(420, viewport.width - 2 * MARGIN);
  let top: number;
  let left: number;
  if (compact) {
    top = viewport.height - size.height - MARGIN;
    left = MARGIN;
  } else if (!rect) {
    top = Math.max(MARGIN, (viewport.height - size.height) / 2);
    left = (viewport.width - width) / 2;
  } else {
    const below = rect.top + rect.height + PAD + GAP;
    const above = rect.top - PAD - GAP - size.height;
    const besideTop = Math.min(Math.max(MARGIN, rect.top + rect.height / 2 - size.height / 2), viewport.height - size.height - MARGIN);
    const rightSpace = viewport.width - (rect.left + rect.width + PAD + GAP) - MARGIN;
    const leftSpace = rect.left - PAD - GAP - MARGIN;
    left = rect.left + rect.width - width;
    if (below + size.height <= viewport.height - MARGIN) top = below;
    else if (above >= MARGIN) top = above;
    else if (rightSpace >= width) {
      top = besideTop;
      left = rect.left + rect.width + PAD + GAP;
    } else if (leftSpace >= width) {
      top = besideTop;
      left = rect.left - PAD - GAP - width;
    } else top = viewport.height - size.height - MARGIN;
  }
  left = Math.min(Math.max(MARGIN, left), viewport.width - width - MARGIN);
  top = Math.max(MARGIN, top);

  const spot = rect && {
    top: Math.max(rect.top - PAD, 4),
    left: Math.max(rect.left - PAD, 4),
    width: Math.min(rect.width + 2 * PAD, viewport.width - 8),
    height: Math.min(rect.height + 2 * PAD, viewport.height - Math.max(rect.top - PAD, 4) - 4),
  };

  return (
    <div className="fixed inset-0 z-50" data-testid="tour">
      {/* blocks the page while the tour is open; the dim comes from the spotlight's shadow */}
      <div className={`absolute inset-0 ${spot ? "" : "bg-slate-950/55"}`} aria-hidden onClick={(e) => e.stopPropagation()} />
      {spot && (
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-xl ring-2 ring-brand-500 motion-safe:transition-all motion-safe:duration-200"
          style={{ ...spot, boxShadow: "0 0 0 9999px rgb(2 6 23 / 0.55)" }}
        />
      )}
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="absolute flex max-h-[55vh] flex-col sm:max-h-[calc(100vh-2rem)] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl outline-none motion-safe:transition-[top,left] motion-safe:duration-200"
        style={{ top, left, width }}
      >
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 bg-brand-50/60 px-5 py-2.5">
          <span className="text-xs font-medium text-brand-700">
            راهنمای {tourTitle} · {faNumber(index + 1)} از {faNumber(steps.length)}
          </span>
          <button type="button" onClick={onClose} className="btn-ghost" aria-label="بستن راهنما">
            ✕
          </button>
        </div>
        <div id={bodyId} className="flex flex-col gap-3 overflow-y-auto px-5 py-4 text-sm leading-7 text-slate-700">
          <h2 id={titleId} className="text-base font-bold text-slate-900">
            {step.title}
          </h2>
          <p>{step.what}</p>
          {step.how && step.how.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-900">چطور کار کنید</div>
              <ul className="flex list-disc flex-col gap-1 ps-5 marker:text-brand-500">
                {step.how.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}
          {step.behind && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="mb-0.5 text-xs font-semibold text-slate-900">پشت صحنه چه اتفاقی می‌افتد</div>
              <p className="text-[13px] leading-6 text-slate-700">{step.behind}</p>
            </div>
          )}
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-5 py-3">
          <div className="flex gap-1" aria-hidden>
            {steps.map((s, i) => (
              <span key={`${s.title}-${i}`} className={`h-1.5 rounded-full ${i === index ? "w-4 bg-brand-600" : "w-1.5 bg-slate-300"}`} />
            ))}
          </div>
          <div className="flex gap-2">
            {index > 0 && (
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => onIndex(index - 1)}>
                قبلی
              </button>
            )}
            {last ? (
              <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
                پایان
              </button>
            ) : (
              <button type="button" className="btn btn-primary btn-sm" onClick={() => onIndex(index + 1)}>
                بعدی
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
