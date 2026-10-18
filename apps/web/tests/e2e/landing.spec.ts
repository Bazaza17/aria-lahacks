import { test, expect } from "@playwright/test";

test.describe("Landing", () => {
  test("hero, links into the app, no page errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Know the building");
    await expect(page.getByRole("link", { name: /Open Dashboard/ }).first()).toHaveAttribute(
      "href",
      "/dashboard",
    );
    await expect(page.getByRole("link", { name: /Live response/ }).first()).toHaveAttribute(
      "href",
      "/live/view",
    );
    // The sections below the fold render.
    await expect(page.getByText(/How it works/i).first()).toBeAttached();

    await page
      .getByRole("link", { name: /Open Dashboard/ })
      .first()
      .click();
    await expect(page).toHaveURL(/\/dashboard$/);

    expect(errors).toEqual([]);
  });
});
