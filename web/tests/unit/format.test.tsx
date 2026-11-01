import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { Money, ModelName, ProductLabel, When } from "@/components/format";
import { faNumber, jalali, parseTomanToRial, percent, relativeTime, toman } from "@/lib/format";

describe("Persian formatting", () => {
  test("amounts in Toman with Persian digits and separators", () => {
    expect(toman(84_000_000)).toBe("۸٬۴۰۰٬۰۰۰ تومان");
    expect(toman(null)).toBe("—");
    expect(faNumber(1405)).toBe("۱٬۴۰۵");
    expect(percent(98.5)).toBe("۹۸٫۵٪");
  });

  test("Jalali date-time in Tehran time", () => {
    // 2026-10-26 08:00 UTC = 1405/08/04 11:30 Asia/Tehran
    expect(jalali("2026-10-26T08:00:00Z")).toBe("۱۴۰۵/۰۸/۰۴، ۱۱:۳۰");
  });

  test("relative time", () => {
    const now = new Date("2026-10-26T08:00:00Z");
    expect(relativeTime("2026-10-26T07:52:00Z", now)).toBe("۸ دقیقه پیش");
    expect(relativeTime("2026-10-26T05:00:00Z", now)).toBe("۳ ساعت پیش");
  });

  test("Toman input with Persian digits becomes Rial", () => {
    expect(parseTomanToRial("۸٬۵۵۰٬۰۰۰")).toBe(85_500_000);
    expect(parseTomanToRial("8,550,000")).toBe(85_500_000);
    expect(parseTomanToRial("abc")).toBeNull();
    expect(parseTomanToRial("0")).toBeNull();
  });
});

describe("format components", () => {
  test("mixed-direction product name renders LTR without reordering", () => {
    const { container } = render(
      <p>
        رم <ProductLabel brand="Kingston" model="DDR5" attributes={{ capacity: "32GB", frequency: "5600" }} />
      </p>,
    );
    const bdi = container.querySelector("bdi");
    expect(bdi).not.toBeNull();
    expect(bdi).toHaveAttribute("dir", "ltr");
    expect(bdi?.textContent).toBe("Kingston DDR5 · 32GB / 5600");
  });

  test("model names are isolated LTR", () => {
    render(<ModelName>990 PRO</ModelName>);
    expect(screen.getByText("990 PRO").tagName).toBe("BDI");
  });

  test("relative time keeps the absolute Jalali time on hover", () => {
    render(<When at="2026-10-26T07:52:00Z" now={new Date("2026-10-26T08:00:00Z")} />);
    const time = screen.getByText("۸ دقیقه پیش");
    expect(time).toHaveAttribute("title", "۱۴۰۵/۰۸/۰۴، ۱۱:۲۲");
    expect(time).toHaveAttribute("dateTime", "2026-10-26T07:52:00Z");
  });

  test("money in Toman", () => {
    render(<Money rial={85_500_000} />);
    expect(screen.getByText("۸٬۵۵۰٬۰۰۰ تومان")).toBeInTheDocument();
  });
});
