/** Persian labels for API enums. */

export const OUTCOME_FA: Record<string, string> = {
  increase: "افزایش قیمت",
  decrease: "کاهش قیمت",
  hold: "بدون تغییر",
  insufficient_data: "داده ناکافی",
  floor_conflict: "تعارض با کف سود",
};

export const STATUS_FA: Record<string, string> = {
  needs_review: "نیازمند بررسی",
  awaiting_override: "در انتظار تأیید مدیر",
  decided: "تصمیم ثبت شد",
  awaiting_verification: "در انتظار مشاهده روی سایت",
  verification_overdue: "مشاهده روی سایت دیر شده",
  verified: "روی سایت تأیید شد",
  override_pending: "در انتظار تأیید مدیر",
  override_rejected: "زیر کف رد شد؛ تصمیم تازه لازم است",
};

export const ALERT_FA: Record<string, string> = {
  floor_conflict: "تعارض با کف سود",
  source_failure: "دریافت ناموفق از منبع",
  stale_data: "داده قدیمی",
};

export const MARKET_LABEL_FA: Record<string, string> = {
  stale: "قدیمی",
  failed: "دریافت ناموفق",
};

export const TIER_FA: Record<string, string> = { A: "الف", B: "ب", C: "ج" };

export const DECISION_TYPE_FA: Record<string, string> = {
  accept: "پذیرش",
  accept_modified: "پذیرش با تغییر",
  reject: "رد",
  defer: "تعویق",
};

export const STAGE_FA: Record<string, string> = {
  reported_done: "انجام‌شده (گزارش کارشناس)",
  observed_on_site: "مشاهده‌شده روی سایت",
  reflected_in_channel: "منعکس‌شده در کانال مقایسه",
  verification_overdue: "مشاهده روی سایت دیر شده",
};

export const VERDICT_FA: Record<string, string> = {
  approved: "تأیید مدیر",
  rejected: "رد مدیر",
  self_approved: "ثبت مستقیم مدیر",
};

export const MATCH_STATE_FA: Record<string, string> = {
  proposed: "پیشنهادی",
  confirmed: "تأییدشده",
  rejected: "ردشده",
  needs_review: "نیازمند بررسی",
};

export const STOCK_FA: Record<string, string> = {
  in_stock: "موجود",
  out_of_stock: "ناموجود",
  unknown: "نامشخص",
};

export const ATTRIBUTE_FA: Record<string, string> = {
  brand: "برند",
  model: "مدل",
  capacity: "ظرفیت",
  generation: "نسل",
  frequency: "فرکانس",
  colour_edition: "رنگ / نسخه",
  warranty_provider: "شرکت گارانتی",
  warranty_months: "مدت گارانتی (ماه)",
  condition: "وضعیت کالا",
  payment: "شرایط پرداخت",
  mpn: "شماره قطعه",
  gtin: "بارکد",
};

export const QUEUE_STATUSES = [
  "needs_review",
  "awaiting_override",
  "decided",
  "awaiting_verification",
  "verification_overdue",
] as const;

export function label(map: Record<string, string>, key: string | null | undefined): string {
  if (!key) return "—";
  return map[key] ?? key;
}
