import { expect, test } from "@playwright/test";

const routes = [
  "/home",
  "/data/catalog",
  "/data/mine",
  "/data/uploads",
  "/apps/investment-prioritisation/overview",
  "/apps/investment-prioritisation/runs",
  "/help",
];

test("core deep links render without browser errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  for (const route of routes) {
    const response = await page.goto(route, { waitUntil: "networkidle" });
    expect(response?.ok(), `${route} should return an HTTP success`).toBeTruthy();
    await expect(page.locator("#root")).not.toBeEmpty();
    await expect(page.getByText("Page not found", { exact: true })).toHaveCount(0);
  }
  expect(errors).toEqual([]);
});

test("mobile routes do not overflow horizontally", async ({ page }) => {
  for (const route of ["/home", "/data/catalog", "/apps/investment-prioritisation/overview"]) {
    await page.goto(route, { waitUntil: "networkidle" });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${route} horizontal overflow`).toBeLessThanOrEqual(1);
  }
});
