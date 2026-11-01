import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import Home from "@/app/page";

test("home page states that no store price is changed", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("دستیار کارشناس قیمت‌گذاری");
  expect(screen.getByText(/هیچ قیمتی را در فروشگاه تغییر/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "ورود به صف بررسی" })).toHaveAttribute("href", "/queue");
});
