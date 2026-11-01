import { ALERT_FA, OUTCOME_FA, STATUS_FA, label } from "@/lib/labels";

const OUTCOME_STYLE: Record<string, string> = {
  floor_conflict: "bg-rose-50 text-rose-700 ring-rose-600/20",
  decrease: "bg-amber-50 text-amber-800 ring-amber-600/20",
  increase: "bg-sky-50 text-sky-700 ring-sky-600/20",
  hold: "bg-slate-50 text-slate-700 ring-slate-500/20",
  insufficient_data: "bg-slate-100 text-slate-600 ring-slate-500/20",
};

const STATUS_STYLE: Record<string, string> = {
  needs_review: "bg-orange-50 text-orange-700 ring-orange-600/20",
  awaiting_override: "bg-violet-50 text-violet-700 ring-violet-600/20",
  override_pending: "bg-violet-50 text-violet-700 ring-violet-600/20",
  override_rejected: "bg-rose-50 text-rose-700 ring-rose-600/20",
  decided: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  awaiting_verification: "bg-blue-50 text-blue-700 ring-blue-600/20",
  verification_overdue: "bg-rose-50 text-rose-700 ring-rose-600/20",
  verified: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
};

const NEUTRAL = "bg-slate-50 text-slate-700 ring-slate-500/20";

export function Pill({ text, className, dot = false }: { text: string; className?: string; dot?: boolean }) {
  return <span className={`badge ${dot ? "badge-dot" : ""} ${className ?? NEUTRAL}`}>{text}</span>;
}

export function OutcomeBadge({ outcome }: { outcome: string }) {
  return <Pill text={label(OUTCOME_FA, outcome)} className={OUTCOME_STYLE[outcome]} />;
}

export function StatusBadge({ status }: { status: string }) {
  return <Pill dot text={label(STATUS_FA, status)} className={STATUS_STYLE[status]} />;
}

export function AlertBadges({ alerts }: { alerts: string[] }) {
  if (!alerts.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {alerts.map((a) => (
        <span
          key={a}
          role="img"
          aria-label={label(ALERT_FA, a)}
          title={label(ALERT_FA, a)}
          className="badge bg-rose-50 text-rose-700 ring-rose-600/25"
        >
          <svg aria-hidden viewBox="0 0 20 20" fill="currentColor" className="size-3.5">
            <path
              fillRule="evenodd"
              d="M8.5 3.5a1.7 1.7 0 013 0l6 10.5A1.7 1.7 0 0116 16.5H4a1.7 1.7 0 01-1.5-2.5l6-10.5zM10 7a.8.8 0 00-.8.8v3a.8.8 0 001.6 0v-3A.8.8 0 0010 7zm0 7a1 1 0 100-2 1 1 0 000 2z"
              clipRule="evenodd"
            />
          </svg>
          {label(ALERT_FA, a)}
        </span>
      ))}
    </span>
  );
}
