/**
 * Persian formatting: Persian digits, Toman amounts, Jalali dates (Asia/Tehran) and relative
 * times. Amounts arrive from the API in integer Rial; the UI shows Toman (Rial ÷ 10).
 */

const TEHRAN = "Asia/Tehran";
const numberFa = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 });
const decimalFa = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
const relativeFa = new Intl.RelativeTimeFormat("fa", { numeric: "auto" });
const jalaliFa = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: TEHRAN,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function faNumber(value: number, decimals = false): string {
  return (decimals ? decimalFa : numberFa).format(value);
}

/** «۸٬۴۰۰٬۰۰۰ تومان» from 84,000,000 Rial. */
export function toman(rial: number | null | undefined): string {
  if (rial === null || rial === undefined) return "—";
  return `${numberFa.format(Math.round(rial / 10))} تومان`;
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${decimalFa.format(value)}٪`;
}

/** Absolute Jalali date-time in Tehran time, e.g. «۱۴۰۵/۰۸/۰۴، ۱۴:۳۰» (same in every runtime). */
export function jalali(value: string | Date): string {
  const parts = Object.fromEntries(
    jalaliFa.formatToParts(typeof value === "string" ? new Date(value) : value).map((p) => [p.type, p.value]),
  );
  return `${parts.year}/${parts.month}/${parts.day}، ${parts.hour}:${parts.minute}`;
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** «۸ دقیقه پیش» */
export function relativeTime(value: string | Date, now: Date = new Date()): string {
  const seconds = Math.round(((typeof value === "string" ? new Date(value) : value).getTime() - now.getTime()) / 1000);
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return relativeFa.format(Math.trunc(seconds / size), unit);
  }
  return relativeFa.format(0, "minute");
}

export function minutes(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  return `${decimalFa.format(seconds / 60)} دقیقه`;
}

const DIGITS: Record<string, string> = {
  "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
  "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
};

/** Parse a Toman amount typed with Persian or ASCII digits and separators; returns Rial. */
export function parseTomanToRial(input: string): number | null {
  const ascii = input.replace(/[۰-۹٠-٩]/g, (d) => DIGITS[d] ?? d).replace(/[\s,٬]/g, "");
  if (!/^\d{1,13}$/.test(ascii)) return null;
  const tomanValue = Number(ascii);
  return tomanValue > 0 ? tomanValue * 10 : null;
}
