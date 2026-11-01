import type { Decision, HistoryItem } from "@/lib/api/schemas";
import { DECISION_TYPE_FA, STAGE_FA, VERDICT_FA, label } from "@/lib/labels";
import { minutes } from "@/lib/format";
import { OutcomeBadge, StatusBadge } from "./badges";
import { Money, When } from "./format";

const STAGES = ["reported_done", "observed_on_site", "reflected_in_channel", "verification_overdue"] as const;

/** Override review state of one decision: pending, approved, rejected or self-approved. */
export function OverrideState({ decision }: { decision: Decision }) {
  if (!decision.below_floor_override) return null;
  const review = decision.override_review;
  return (
    <div data-testid="override-state" className="text-sm">
      <span className="font-medium">قیمت زیر کف: </span>
      {review ? (
        <span>
          {label(VERDICT_FA, review.verdict)} — <bdi>{review.actor}</bdi>: {review.reason} (<When at={review.created_at} />)
        </span>
      ) : (
        <span>در انتظار تأیید مدیر</span>
      )}
      {decision.override_reason && <div className="text-slate-600">دلیل درخواست: {decision.override_reason}</div>}
    </div>
  );
}

/** The three outcome stages plus overdue, each reached (with time and delay) or pending. */
export function OutcomeStages({ decision }: { decision: Decision }) {
  if (decision.type !== "accept" && decision.type !== "accept_modified") return null;
  const reached = new Map(decision.outcomes.map((o) => [o.stage, o]));
  return (
    <ol className="flex flex-col gap-1 text-sm" aria-label="مراحل اجرا">
      {STAGES.filter((s) => s !== "verification_overdue" || reached.has(s)).map((stage) => {
        const outcome = reached.get(stage);
        return (
          <li key={stage} data-stage={stage} data-reached={outcome ? "yes" : "no"}>
            <span aria-hidden>{outcome ? (stage === "verification_overdue" ? "⚠" : "✓") : "…"}</span>{" "}
            {label(STAGE_FA, stage)}
            {outcome ? (
              <>
                {" — "}
                <When at={outcome.occurred_at} />
                {outcome.delay_seconds !== null && <> (تأخیر {minutes(outcome.delay_seconds)})</>}
              </>
            ) : (
              " — در انتظار"
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function DecisionCard({ decision }: { decision: Decision }) {
  return (
    <article className="card p-4" data-decision={decision.id}>
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{label(DECISION_TYPE_FA, decision.type)}</span>
        <StatusBadge status={decision.status} />
        <span className="text-sm text-slate-600">
          <bdi>{decision.actor}</bdi> — <When at={decision.created_at} />
        </span>
        {decision.superseded_by && <span className="text-xs text-slate-500">(اصلاح‌شده با تصمیم بعدی)</span>}
      </header>
      <p className="text-sm">{decision.reason}</p>
      {decision.applied_price_rial !== null && (
        <p className="text-sm">
          قیمت اعمال‌شده: <Money rial={decision.applied_price_rial} /> — کف: <Money rial={decision.floor_rial} />
        </p>
      )}
      <OverrideState decision={decision} />
      <OutcomeStages decision={decision} />
    </article>
  );
}

export function DecisionHistory({ history }: { history: HistoryItem[] }) {
  if (!history.length) return <p className="text-slate-600">هنوز پیشنهادی ثبت نشده است.</p>;
  return (
    <ol className="flex flex-col gap-3" aria-label="تاریخچه">
      {[...history].reverse().map(({ recommendation: rec, decisions }) => (
        <li key={rec.id} className="card p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <OutcomeBadge outcome={rec.outcome} />
            <When at={rec.evaluated_at} />
            <span>
              قیمت ما <Money rial={rec.our_price_rial} /> · بازار <Money rial={rec.market_ref_rial} /> · پیشنهاد{" "}
              <Money rial={rec.suggested_price_rial} /> · کف <Money rial={rec.floor_rial} />
            </span>
            {rec.superseded_by && <span className="text-xs text-slate-500">(نسخه قدیمی)</span>}
          </div>
          {decisions.length > 0 && (
            <div className="mt-2 flex flex-col gap-2">
              {decisions.map((d) => (
                <DecisionCard key={d.id} decision={d} />
              ))}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
