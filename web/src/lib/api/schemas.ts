/**
 * Runtime validation of API responses. TypeScript types come from the generated OpenAPI schema;
 * these Zod schemas check at runtime that responses still have that shape, so a drifted or
 * broken response fails loudly instead of rendering wrong numbers.
 */
import { z } from "zod";

const id = z.uuid();
const when = z.iso.datetime({ offset: true });
const rial = z.number().int().nullable();

export const ProblemSchema = z.looseObject({
  type: z.string(),
  status: z.number().int(),
  message_fa: z.string().optional(),
  detail: z.string().optional(),
  current_recommendation_id: z.string().optional(),
});

export const ScoreSchema = z.object({
  score: z.number().int(),
  tier_multiplier: z.number().int(),
  outcome_weight: z.number().int(),
  profit_impact_rial: z.number().int(),
  profit_points: z.number().int(),
  open_since: when,
  age_hours: z.number().int(),
  age_points: z.number().int(),
});

export const QueueItemSchema = z.object({
  variant_id: id,
  sku: z.string(),
  product_name: z.string(),
  brand: z.string(),
  model: z.string(),
  category: z.string(),
  tier: z.enum(["A", "B", "C"]),
  attributes: z.record(z.string(), z.unknown()),
  recommendation_id: id,
  outcome: z.enum(["increase", "decrease", "hold", "insufficient_data", "floor_conflict"]),
  reason_code: z.string(),
  flags: z.array(z.string()),
  our_price_rial: rial,
  market_ref_rial: rial,
  market_label: z.enum(["stale", "failed"]).nullable(),
  suggested_price_rial: rial,
  floor_rial: rial,
  ceiling_rial: rial,
  evaluated_at: when,
  status: z.enum([
    "needs_review",
    "awaiting_override",
    "decided",
    "awaiting_verification",
    "verification_overdue",
    "verified",
  ]),
  decision_id: id.nullable(),
  alerts: z.array(z.enum(["floor_conflict", "source_failure", "stale_data"])),
  score: ScoreSchema,
});
export type QueueItem = z.infer<typeof QueueItemSchema>;

export const QueuePageSchema = z.object({
  items: z.array(QueueItemSchema),
  total: z.number().int(),
  next_cursor: z.string().nullable(),
});

export const CardsSchema = z.array(
  z.object({
    key: z.string(),
    title_fa: z.string(),
    count: z.number().int(),
    primary: z.boolean(),
    target: z.enum(["queue", "matches"]),
    filter: z.record(z.string(), z.union([z.string(), z.array(z.string())])),
  }),
);
export type Card = z.infer<typeof CardsSchema>[number];

export const EvidenceRowSchema = z.object({
  observation_id: id,
  tracked_offer_id: id,
  source_id: id,
  source_name: z.string(),
  url: z.string(),
  seller: z.string().nullable(),
  title: z.string().nullable(),
  price_rial: rial,
  stock_state: z.string(),
  conditions: z.record(z.string(), z.unknown()),
  observed_at: when,
  age_seconds: z.number().int(),
  freshness: z.enum(["fresh", "stale", "failed", "never_observed"]),
  match_version_id: id,
  match_state: z.string(),
  match_flags: z.array(z.string()),
  flags: z.array(z.string()),
  qualifies: z.boolean(),
  is_market_reference: z.boolean(),
  reasons: z.array(z.string()),
  reasons_fa: z.array(z.string()),
  evidence: z.array(z.object({ id, kind: z.string(), url: z.string().nullable() })),
});
export type EvidenceRow = z.infer<typeof EvidenceRowSchema>;

export const DecisionSummarySchema = z.object({
  id,
  recommendation_id: id,
  type: z.string(),
  status: z.string(),
  applied_price_rial: rial,
  below_floor_override: z.boolean(),
  actor: z.string(),
  created_at: when,
});

export const ItemDetailSchema = z.object({
  item: QueueItemSchema,
  explanation: z.string(),
  explanation_llm: z.string().nullable(),
  qualifying_count: z.number().int(),
  median_rial: rial,
  excluded_outlier_ids: z.array(id),
  profit_current_rial: rial,
  profit_suggested_rial: rial,
  engine_version: z.string(),
  inputs_purged: z.boolean(),
  evidence: z.array(EvidenceRowSchema),
  decision: DecisionSummarySchema.nullable(),
});
export type ItemDetail = z.infer<typeof ItemDetailSchema>;

const OutcomeSchema = z.object({
  stage: z.enum(["reported_done", "observed_on_site", "reflected_in_channel", "verification_overdue"]),
  occurred_at: when,
  actor: z.string().nullable(),
  observation_id: id.nullable(),
  delay_seconds: z.number().int().nullable(),
});

export const DecisionSchema = z.object({
  id,
  variant_id: id,
  recommendation_id: id,
  type: z.enum(["accept", "accept_modified", "reject", "defer"]),
  reason: z.string(),
  applied_price_rial: rial,
  floor_rial: rial,
  below_floor_override: z.boolean(),
  override_reason: z.string().nullable(),
  supersedes_decision_id: id.nullable(),
  superseded_by: id.nullable(),
  actor: z.string(),
  created_at: when,
  status: z.enum([
    "decided",
    "override_pending",
    "override_rejected",
    "awaiting_verification",
    "verification_overdue",
    "verified",
  ]),
  override_review: z
    .object({
      verdict: z.enum(["approved", "rejected", "self_approved"]),
      reason: z.string(),
      actor: z.string(),
      created_at: when,
    })
    .nullable(),
  outcomes: z.array(OutcomeSchema),
});
export type Decision = z.infer<typeof DecisionSchema>;

export const HistorySchema = z.array(
  z.object({
    recommendation: z.object({
      id,
      outcome: z.string(),
      reason_code: z.string(),
      suggested_price_rial: rial,
      our_price_rial: rial,
      floor_rial: rial,
      market_ref_rial: rial,
      explanation: z.string(),
      evaluated_at: when,
      superseded_by: id.nullable(),
    }),
    decisions: z.array(DecisionSchema),
  }),
);
export type HistoryItem = z.infer<typeof HistorySchema>[number];

const VariantRefSchema = z.object({
  id,
  sku: z.string(),
  product_name: z.string(),
  brand: z.string(),
  model: z.string(),
});

export const MatchQueueSchema = z.object({
  matches: z.array(
    z.object({
      match_version_id: id,
      state: z.enum(["proposed", "needs_review"]),
      flags: z.array(z.string()),
      confidence_bp: z.number().int(),
      decided_by: z.string(),
      reason: z.string().nullable(),
      variant: VariantRefSchema,
      tracked_offer_id: id,
      url: z.string(),
      source_name: z.string(),
      seller_key: z.string(),
      title: z.string().nullable(),
      price_rial: rial,
      observed_at: when.nullable(),
      attributes: z.array(
        z.object({
          name: z.string(),
          ours: z.union([z.string(), z.number()]).nullable(),
          theirs: z.union([z.string(), z.number()]).nullable(),
          source: z.string().nullable(),
          state: z.enum(["equal", "different", "missing_offer", "missing_ours"]),
        }),
      ),
    }),
  ),
  suggested_offers: z.array(
    z.object({
      tracked_offer_id: id,
      url: z.string(),
      source_name: z.string(),
      variant: VariantRefSchema,
      suggested_by: z.string().nullable(),
      rationale: z.string().nullable(),
      created_at: when,
    }),
  ),
});
export type MatchQueue = z.infer<typeof MatchQueueSchema>;

export const VariantListSchema = z.array(
  VariantRefSchema.extend({ category: z.string(), importance_tier: z.string() }),
);

export const ReviewSessionSchema = z.object({ id, closed_at: when.nullable() });

export const RecheckSchema = z.object({
  id,
  status: z.enum(["pending", "completed", "failed"]),
  tracked_offer_id: id,
});

/** Loose validation for admin/report payloads: required identity fields only. */
export const LooseListSchema = z.array(z.looseObject({}));
export const LooseObjectSchema = z.looseObject({});

// --- admin ------------------------------------------------------------------------------------------

export const ImportReportSchema = z.object({
  id,
  file_name: z.string(),
  status: z.string(),
  rows_total: z.number().int(),
  rows_created: z.number().int(),
  rows_updated: z.number().int(),
  rows_unchanged: z.number().int(),
  rows_rejected: z.number().int(),
  rows_held: z.number().int(),
  errors: z.array(z.object({ row: z.number().int().nullable(), column: z.string().nullable(), message_fa: z.string() })),
  uploaded_by: z.string(),
  created_at: when,
});
export type ImportReport = z.infer<typeof ImportReportSchema>;

export const CostRecordSchema = z.object({
  id,
  variant_id: id,
  import_id: id.nullable(),
  purchase_cost_rial: z.number().int(),
  previous_cost_rial: rial,
  state: z.enum(["applied", "held", "confirmed", "rejected"]),
  uploaded_by: z.string(),
  created_at: when,
});

export const RuleVersionSchema = z.looseObject({
  id,
  scope: z.enum(["default", "category", "variant"]),
  scope_key: z.string().nullable(),
  version: z.number().int(),
  reason: z.string().nullable(),
  created_by: z.string(),
  created_at: when,
});
export type RuleVersion = z.infer<typeof RuleVersionSchema> & Record<string, unknown>;

export const SourceSchema = z.object({
  id,
  name: z.string(),
  base_domain: z.string(),
  connector_key: z.string(),
  method: z.enum(["api", "html", "rendered_page"]),
  currency_unit: z.enum(["RIAL", "TOMAN"]),
  quota_per_minute: z.number().int(),
  interval_a_seconds: z.number().int(),
  interval_b_seconds: z.number().int(),
  interval_c_seconds: z.number().int(),
  status: z.enum(["candidate", "under_evaluation", "approved", "suspended", "rejected"]),
  status_reason: z.string().nullable(),
});
export type Source = z.infer<typeof SourceSchema>;

export const ClearanceSchema = z.object({
  id,
  kind: z.string(),
  approver_name: z.string().nullable(),
  approved_on: z.string().nullable(),
  scope: z.string().nullable(),
  reference: z.string().nullable(),
  permitted_requests_per_minute: z.number().int().nullable(),
  recorded_by: z.string(),
  created_at: when,
});

export const SourceHealthSchema = z.object({
  source_id: id,
  name: z.string(),
  status: z.string(),
  requests: z.number().int(),
  successes: z.number().int(),
  success_rate: z.number().nullable(),
  blocked: z.number().int(),
  data_age_median_seconds: z.number().int().nullable(),
  estimated_cost_rial: z.number().int(),
});

export const ExtractionRuleSchema = z.object({
  id,
  source_id: id,
  version: z.number().int(),
  config: z.record(z.string(), z.unknown()),
  state: z.enum(["proposed", "active", "retired", "rejected"]),
  origin: z.enum(["admin", "llm"]),
  validation: z.looseObject({ passed: z.boolean() }).nullable(),
  created_by: z.string(),
  created_at: when,
});

export const QualificationRunSchema = z.object({
  id,
  status: z.enum(["running", "completed"]),
  source_ids: z.array(id),
  report: z.record(z.string(), z.unknown()).nullable(),
  started_at: when,
});

// --- reports ---------------------------------------------------------------------------------------

const Accuracy = z.object({ reviewed: z.number().int(), correct: z.number().int(), accuracy_pct: z.number().nullable() });
const Distribution = z.object({
  count: z.number().int(),
  median: z.number().nullable(),
  p90: z.number().nullable(),
  max: z.number().nullable(),
});
const Kpi = z.object({
  key: z.string(),
  value: z.number().nullable(),
  unit: z.string(),
  sample: z.number().int(),
  target: z.number().nullable(),
  source: z.string(),
});
export type KpiValue = z.infer<typeof Kpi>;

export const PilotReportSchema = z.object({
  start: when,
  end: when,
  match_accuracy: z
    .object({
      sample_id: id,
      period: z.string(),
      population: z.number().int(),
      size: z.number().int(),
      overall: Accuracy,
      target_pct: z.number(),
    })
    .nullable(),
  floor_safety: z.object({
    recommendations: z.number().int(),
    below_floor_suggestions: z.number().int(),
    target: z.number(),
    self_approved: z.number().int(),
    overrides: z.array(
      z.object({
        decision_id: id,
        applied_price_rial: rial,
        floor_rial: rial,
        requested_by: z.string(),
        request_reason: z.string().nullable(),
        verdict: z.string().nullable(),
        approver: z.string().nullable(),
        review_reason: z.string().nullable(),
        decided_at: when,
      }),
    ),
  }),
  evidence_completeness: z.object({
    actionable: z.number().int(),
    complete: z.number().int(),
    completeness_pct: z.number().nullable(),
    non_compliant_ids: z.array(id),
    target_pct: z.number(),
  }),
  review_time: z.object({
    decisions: z.number().int(),
    median_seconds: z.number().nullable(),
    p90_seconds: z.number().nullable(),
    low_sample: z.boolean(),
    categories: z.array(
      z.object({
        category: z.string(),
        decisions: z.number().int(),
        median_seconds: z.number().nullable(),
        p90_seconds: z.number().nullable(),
        baseline_seconds: z.number().nullable(),
        low_sample: z.boolean(),
      }),
    ),
    weighted_baseline_seconds: z.number().nullable(),
    weighted_measured_seconds: z.number().nullable(),
    reduction_pct: z.number().nullable(),
    categories_without_baseline: z.array(z.string()),
    target_pct: z.number(),
  }),
});
export type PilotReport = z.infer<typeof PilotReportSchema>;

export const WeeklyReportSchema = z.object({
  start: when,
  end: when,
  sources: z.array(
    z.object({
      source_id: id,
      name: z.string(),
      requests: z.number().int(),
      success_rate: z.number().nullable(),
      blocked: z.number().int(),
      data_age_median_seconds: z.number().nullable(),
      estimated_cost_rial: z.number().int(),
    }),
  ),
  llm: z.array(
    z.object({
      task: z.string(),
      model: z.string(),
      calls: z.number().int(),
      ok: z.number().int(),
      input_tokens: z.number().int(),
      output_tokens: z.number().int(),
      cost_rial: z.number().nullable(),
    }),
  ),
  backlog: z.record(z.string(), z.number().int()),
  recommendation_to_decision_seconds: Distribution,
  tier_a_data_age_seconds: Distribution,
  site_delay_seconds: Distribution,
  channel_delay_seconds: Distribution,
  kpis: z.array(Kpi),
});
export type WeeklyReport = z.infer<typeof WeeklyReportSchema>;

export const AuditSchema = z.object({
  id,
  period: z.string(),
  population: z.number().int(),
  size: z.number().int(),
  overall: Accuracy,
  target_pct: z.number(),
  items: z.array(
    z.object({
      id,
      match_version_id: id,
      category: z.string(),
      confidence_band: z.string(),
      verdict: z.enum(["correct", "incorrect"]).nullable(),
      note: z.string().nullable(),
    }),
  ),
  incorrect: z.array(z.object({ id, match_version_id: id, note: z.string().nullable() })),
});

export const TrackedOfferSchema = z.object({
  id,
  source_id: id,
  variant_id: id,
  url: z.string(),
  external_id: z.string().nullable(),
  status: z.enum(["suggested", "active", "dismissed", "paused"]),
  is_own_store: z.boolean(),
  is_own_channel: z.boolean(),
  next_due_at: when.nullable(),
  created_by: z.string(),
  created_at: when,
});
export type TrackedOffer = z.infer<typeof TrackedOfferSchema>;

export const CostComponentSchema = z.object({
  id,
  name: z.string(),
  amount_rial: z.number().int(),
  category: z.string().nullable(),
  active: z.boolean(),
  created_by: z.string(),
  created_at: when,
  deactivated_by: z.string().nullable(),
  deactivated_at: when.nullable(),
});

export const BaselineSchema = z.object({
  category: z.string(),
  median_seconds: z.number().int(),
  note: z.string().nullable(),
  entered_by: z.string(),
  created_at: when,
});

const percentTarget = z.number().nullable();
export const TenantSettingsSchema = z.object({
  recheck_daily_budget_per_user: z.number().int(),
  verification_window_minutes: z.number().int(),
  evidence_retention_days: z.number().int(),
  observation_retention_days: z.number().int().nullable(),
  kpi_targets: z.object({
    tier_a_coverage_pct: percentTarget,
    tier_a_data_age_p90_minutes: z.number().int().nullable(),
    verification_reliability_pct: percentTarget,
    source_success_rate_pct: percentTarget,
  }),
});
export type TenantSettings = z.infer<typeof TenantSettingsSchema>;
