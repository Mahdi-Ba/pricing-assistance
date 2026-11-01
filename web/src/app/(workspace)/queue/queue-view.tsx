"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useId, useRef, type KeyboardEvent } from "react";
import { AlertBadges, OutcomeBadge, StatusBadge } from "@/components/badges";
import { FaNum, Money, ProductLabel } from "@/components/format";
import { ErrorNotice, Loading } from "@/components/notices";
import { PageHeading } from "@/components/tour/help-button";
import { api, unwrap } from "@/lib/api/client";
import { CardsSchema, QueuePageSchema, type QueueItem } from "@/lib/api/schemas";
import { faNumber } from "@/lib/format";
import { MARKET_LABEL_FA, OUTCOME_FA, QUEUE_STATUSES, STATUS_FA, TIER_FA } from "@/lib/labels";
import { cardHref, filtersFrom, toSearchParams, type FilterKey, type Filters } from "@/lib/queue-filters";

const SOURCE_HEALTH_FA: Record<string, string> = {
  attention: "قدیمی یا ناموفق",
  failing: "دریافت ناموفق",
  stale: "داده قدیمی",
  ok: "سالم",
};
const PRICE_POSITION_FA: Record<string, string> = {
  above_market: "گران‌تر از بازار",
  below_market: "ارزان‌تر از بازار",
};

function conditions(item: QueueItem): string {
  const months = item.attributes.warranty_months;
  const provider = item.attributes.warranty_provider;
  if (typeof months === "number" && typeof provider === "string") {
    return `گارانتی ${faNumber(months)} ماهه ${provider}`;
  }
  return "";
}

function scoreTitle(item: QueueItem): string {
  const s = item.score;
  return (
    `امتیاز اولویت ${faNumber(s.score)} = ${faNumber(s.tier_multiplier)} × ` +
    `(${faNumber(s.outcome_weight)} نتیجه + ${faNumber(s.profit_points)} اثر سود + ${faNumber(s.age_points)} قدمت)`
  );
}

/** Accent per summary card: problem counts turn coloured only when non-zero. */
const CARD_TONE: Record<string, { bar: string; number: string }> = {
  open_decisions: { bar: "before:bg-brand-600", number: "text-brand-700" },
  above_market: { bar: "before:bg-amber-500", number: "text-amber-700" },
  below_market: { bar: "before:bg-sky-500", number: "text-sky-700" },
  floor_conflicts: { bar: "before:bg-rose-500", number: "text-rose-700" },
  source_attention: { bar: "before:bg-orange-500", number: "text-orange-700" },
  overrides_awaiting_approval: { bar: "before:bg-violet-500", number: "text-violet-700" },
  pending_matches: { bar: "before:bg-teal-500", number: "text-teal-700" },
};
const CARD_PRIMARY = { bar: "before:bg-brand-600", number: "text-brand-700" };
const CARD_NEUTRAL = { bar: "before:bg-slate-200", number: "text-slate-500" };

function Cards() {
  const cards = useQuery({
    queryKey: ["queue-summary"],
    queryFn: async () => unwrap(await api.GET("/api/v1/queue/summary"), CardsSchema),
  });
  if (cards.isPending) return <Loading />;
  if (cards.error) return <ErrorNotice error={cards.error} />;
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7" aria-label="خلاصه وضعیت" data-tour="queue-cards">
      {cards.data.map((card) => {
        const tone = card.count > 0 || card.primary ? (CARD_TONE[card.key] ?? CARD_PRIMARY) : CARD_NEUTRAL;
        return (
          <li key={card.key} className="h-full">
            <Link
              href={card.target === "matches" ? "/matches" : cardHref(card.filter)}
              className={`card relative flex h-full flex-col justify-between gap-3 overflow-hidden p-4 transition before:absolute before:inset-y-0 before:start-0 before:w-1 hover:-translate-y-0.5 hover:shadow-md ${tone.bar} ${
                card.primary ? "ring-2 ring-brand-500/30" : ""
              }`}
              data-card={card.key}
            >
              <span className="block text-xs leading-5 font-medium text-slate-500">{card.title_fa}</span>
              <span className={`block text-3xl font-bold ${tone.number}`}>
                <FaNum value={card.count} />
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Select({
  name,
  label,
  options,
  filters,
  onChange,
}: {
  name: FilterKey;
  label: string;
  options: Record<string, string>;
  filters: Filters;
  onChange: (key: FilterKey, value: string) => void;
}) {
  const id = useId();
  return (
    <div className="field-label">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        name={name}
        value={filters[name]?.[0] ?? ""}
        onChange={(e) => onChange(name, e.target.value)}
        className="field min-w-32"
      >
        <option value="">همه</option>
        {Object.entries(options).map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
      </select>
    </div>
  );
}

export function QueueView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const filters = filtersFrom(new URLSearchParams(params.toString()));
  const rows = useRef<(HTMLTableRowElement | null)[]>([]);

  const queue = useInfiniteQuery({
    queryKey: ["queue", params.toString()],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const query = Object.fromEntries(
        Object.entries(filters).map(([k, v]) => [k, v.length === 1 ? v[0] : v]),
      );
      return unwrap(
        await api.GET("/api/v1/queue", {
          params: { query: { ...query, ...(pageParam ? { cursor: pageParam } : {}) } as never },
        }),
        QueuePageSchema,
      );
    },
    getNextPageParam: (last) => last.next_cursor,
  });

  function setFilter(key: FilterKey, value: string) {
    const next = { ...filters, [key]: value ? [value] : [] };
    const query = toSearchParams(next).toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  const items = queue.data?.pages.flatMap((p) => p.items) ?? [];
  const total = queue.data?.pages[0]?.total ?? 0;

  function onKey(event: KeyboardEvent<HTMLTableRowElement>, index: number, item: QueueItem) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = index + (event.key === "ArrowDown" ? 1 : -1);
      rows.current[Math.max(0, Math.min(items.length - 1, next))]?.focus();
    } else if (event.key === "Enter") {
      router.push(`/queue/${item.variant_id}`);
    }
  }

  return (
    <section className="page">
      <PageHeading
        title="صف بررسی قیمت"
        subtitle="پیشنهادهای قیمت به ترتیب اولویت. هیچ قیمتی خودکار در فروشگاه تغییر نمی‌کند."
        tour="queue"
      />
      <Cards />
      <form className="card flex flex-wrap items-end gap-3 p-4" aria-label="فیلترها" data-tour="queue-filters" onSubmit={(e) => e.preventDefault()}>
        <Select name="status" label="وضعیت" options={Object.fromEntries(QUEUE_STATUSES.map((s) => [s, STATUS_FA[s] ?? s]))} filters={filters} onChange={setFilter} />
        <Select name="outcome" label="نتیجه" options={OUTCOME_FA} filters={filters} onChange={setFilter} />
        <Select name="tier" label="اهمیت" options={TIER_FA} filters={filters} onChange={setFilter} />
        <Select name="source_health" label="سلامت منبع" options={SOURCE_HEALTH_FA} filters={filters} onChange={setFilter} />
        <Select name="price_position" label="جایگاه قیمت" options={PRICE_POSITION_FA} filters={filters} onChange={setFilter} />
        <label className="field-label">
          دسته
          <input
            name="category"
            defaultValue={filters.category?.[0] ?? ""}
            onBlur={(e) => setFilter("category", e.target.value.trim())}
            placeholder="مثلاً SSD"
            className="field"
          />
        </label>
      </form>
      {queue.isPending ? (
        <Loading />
      ) : queue.error ? (
        <ErrorNotice error={queue.error} />
      ) : (
        <>
          <p className="muted -mb-3" aria-live="polite">
            <FaNum value={total} /> مورد
          </p>
          <table className="data-table" aria-label="صف بررسی" data-tour="queue-table">
            <thead>
              <tr>
                <th>کالا و شرایط</th>
                <th>قیمت ما</th>
                <th>مرجع بازار</th>
                <th>پیشنهاد</th>
                <th>وضعیت</th>
                <th>اقدام</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => (
                <tr
                  key={item.variant_id}
                  ref={(el) => {
                    rows.current[index] = el;
                  }}
                  tabIndex={0}
                  onKeyDown={(e) => onKey(e, index, item)}
                  className="focus:bg-brand-50 focus:outline-2 focus:-outline-offset-2 focus:outline-brand-500"
                  title={scoreTitle(item)}
                  data-variant={item.variant_id}
                >
                  <td>
                    <div className="font-semibold text-slate-900">{item.product_name}</div>
                    <div className="mb-1 text-xs text-slate-500">
                      <ProductLabel brand={item.brand} model={item.model} attributes={item.attributes} />
                      {conditions(item) ? ` — ${conditions(item)}` : ""}
                    </div>
                    <AlertBadges alerts={item.alerts} />
                  </td>
                  <td className="font-medium">
                    <Money rial={item.our_price_rial} />
                  </td>
                  <td>
                    {item.market_ref_rial !== null ? (
                      <Money rial={item.market_ref_rial} />
                    ) : (
                      <span className="text-xs font-medium text-rose-600">{item.market_label ? MARKET_LABEL_FA[item.market_label] : "—"}</span>
                    )}
                  </td>
                  <td>
                    <div className="flex flex-col items-start gap-1">
                      <OutcomeBadge outcome={item.outcome} />
                      {item.suggested_price_rial !== null && (
                        <span className="font-semibold text-slate-900">
                          <Money rial={item.suggested_price_rial} />
                        </span>
                      )}
                    </div>
                  </td>
                  <td>
                    <StatusBadge status={item.status} />
                  </td>
                  <td>
                    <Link href={`/queue/${item.variant_id}`} className="btn btn-secondary btn-sm" tabIndex={-1} data-tour={index === 0 ? "queue-first-review" : undefined}>
                      بررسی
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {queue.hasNextPage && (
            <button
              type="button"
              onClick={() => queue.fetchNextPage()}
              className="self-center btn btn-secondary"
              disabled={queue.isFetchingNextPage}
            >
              موارد بیشتر
            </button>
          )}
        </>
      )}
    </section>
  );
}
