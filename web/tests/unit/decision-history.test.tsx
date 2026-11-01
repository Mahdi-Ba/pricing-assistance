import { render, screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { DecisionCard } from "@/components/decision-history";
import type { Decision } from "@/lib/api/schemas";

const T0 = "2026-10-26T08:00:00Z";

function decision(overrides: Partial<Decision>): Decision {
  return {
    id: "01a17500-0000-7000-8000-000000000001",
    variant_id: "01a17500-0000-7000-8000-000000000002",
    recommendation_id: "01a17500-0000-7000-8000-000000000003",
    type: "accept_modified",
    reason: "رقابت",
    applied_price_rial: 83_000_000,
    floor_rial: 84_000_000,
    below_floor_override: false,
    override_reason: null,
    supersedes_decision_id: null,
    superseded_by: null,
    actor: "pilot-expert",
    created_at: T0,
    status: "decided",
    override_review: null,
    outcomes: [],
    ...overrides,
  };
}

const override = { below_floor_override: true, override_reason: "فروش ویژه" };
const review = (verdict: "approved" | "rejected" | "self_approved") => ({
  verdict,
  reason: "بررسی شد",
  actor: "pilot-admin",
  created_at: T0,
});
const stage = (name: Decision["outcomes"][number]["stage"], delay: number | null = null) => ({
  stage: name,
  occurred_at: T0,
  actor: name === "reported_done" ? "pilot-expert" : null,
  observation_id: name === "reported_done" ? null : "01a17500-0000-7000-8000-000000000009",
  delay_seconds: delay,
});

describe("override states", () => {
  test.each([
    ["pending", decision({ ...override, status: "override_pending" }), "در انتظار تأیید مدیر"],
    ["approved", decision({ ...override, override_review: review("approved") }), "تأیید مدیر"],
    ["rejected", decision({ ...override, status: "override_rejected", override_review: review("rejected") }), "رد مدیر"],
    ["self-approved", decision({ ...override, override_review: review("self_approved") }), "ثبت مستقیم مدیر"],
  ])("%s", (_, value, text) => {
    render(<DecisionCard decision={value} />);
    expect(within(screen.getByTestId("override-state")).getByText(new RegExp(text))).toBeInTheDocument();
  });

  test("no override block for prices at or above the floor", () => {
    render(<DecisionCard decision={decision({})} />);
    expect(screen.queryByTestId("override-state")).toBeNull();
  });
});

describe("outcome stages", () => {
  function reached(container: HTMLElement): Record<string, string | null> {
    return Object.fromEntries(
      [...container.querySelectorAll("[data-stage]")].map((li) => [li.getAttribute("data-stage"), li.getAttribute("data-reached")]),
    );
  }

  test("reported but not yet observed", () => {
    const { container } = render(
      <DecisionCard decision={decision({ status: "awaiting_verification", outcomes: [stage("reported_done")] })} />,
    );
    expect(reached(container)).toEqual({ reported_done: "yes", observed_on_site: "no", reflected_in_channel: "no" });
    expect(screen.getByText("در انتظار مشاهده روی سایت")).toBeInTheDocument();
  });

  test("observed on site with its delay", () => {
    const { container } = render(
      <DecisionCard
        decision={decision({ status: "verified", outcomes: [stage("reported_done"), stage("observed_on_site", 1200)] })}
      />,
    );
    expect(reached(container).observed_on_site).toBe("yes");
    expect(container.textContent).toContain("تأخیر ۲۰ دقیقه");
  });

  test("reflected in channel reported separately", () => {
    const { container } = render(
      <DecisionCard
        decision={decision({
          status: "verified",
          outcomes: [stage("reported_done"), stage("observed_on_site", 600), stage("reflected_in_channel", 18_000)],
        })}
      />,
    );
    expect(reached(container).reflected_in_channel).toBe("yes");
    expect(container.textContent).toContain("تأخیر ۳۰۰ دقیقه");
  });

  test("overdue", () => {
    const { container } = render(
      <DecisionCard
        decision={decision({ status: "verification_overdue", outcomes: [stage("reported_done"), stage("verification_overdue")] })}
      />,
    );
    expect(reached(container).verification_overdue).toBe("yes");
    expect(screen.getAllByText(/مشاهده روی سایت دیر شده/).length).toBeGreaterThan(0);
  });

  test("reject and defer decisions have no outcome stages", () => {
    const { container } = render(<DecisionCard decision={decision({ type: "reject", applied_price_rial: null })} />);
    expect(container.querySelectorAll("[data-stage]")).toHaveLength(0);
  });
});
