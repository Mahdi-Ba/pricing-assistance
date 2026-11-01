import { faNumber, jalali, relativeTime, toman } from "@/lib/format";

export function Money({ rial }: { rial: number | null | undefined }) {
  return <span className="tabular-nums whitespace-nowrap">{toman(rial)}</span>;
}

export function FaNum({ value }: { value: number }) {
  return <span className="tabular-nums">{faNumber(value)}</span>;
}

/** Relative time with the absolute Jalali date-time available on hover and to assistive tech. */
export function When({ at, now }: { at: string; now?: Date }) {
  const absolute = jalali(at);
  return (
    <time dateTime={at} title={absolute} className="whitespace-nowrap" aria-label={`${relativeTime(at, now)} (${absolute})`}>
      {relativeTime(at, now)}
    </time>
  );
}

/** Latin model names render left-to-right inside the RTL layout without reordering. */
export function ModelName({ children }: { children: string }) {
  return <bdi dir="ltr">{children}</bdi>;
}

/** «Kingston DDR5 · 32GB / 5600» style label: brand, model and key attributes, LTR-isolated. */
export function ProductLabel({
  brand,
  model,
  attributes = {},
}: {
  brand: string;
  model: string;
  attributes?: Record<string, unknown>;
}) {
  const details = ["capacity", "frequency", "generation"]
    .map((k) => attributes[k])
    .filter((v): v is string | number => typeof v === "string" || typeof v === "number");
  const text = details.length ? `${brand} ${model} · ${details.join(" / ")}` : `${brand} ${model}`;
  return <ModelName>{text}</ModelName>;
}
