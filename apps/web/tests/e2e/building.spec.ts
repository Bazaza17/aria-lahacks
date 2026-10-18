import { test, expect } from "@playwright/test";

// The venue's Supabase row (James West Alumni Center); needs the web app and the API's engine.
const VENUE = process.env.NEXT_PUBLIC_VENUE_BUILDING_ID ?? "547b5ec5-30c5-4f76-8080-012a52e90bd9";

test.describe("Venue pre-plan", () => {
  test("scan · fire start · fire clock · size-up", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto(`/building/${VENUE}`);

    await expect(
      page.getByRole("heading", { level: 1, name: /James West Alumni Center/ }),
    ).toBeVisible();
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 90_000 });

    // The panel follows the engine's default start, then a new one.
    await expect(page.getByText("Occupied rooms")).toBeVisible({ timeout: 30_000 });
    const picker = page.getByLabel("Space the fire starts in");
    await picker.selectOption("120");
    await expect(picker).toHaveValue("120");
    await expect(page.getByText(/Fire in Founders' Room/)).toBeVisible({ timeout: 30_000 });

    // Move the fire clock to the end.
    const clock = page.getByRole("slider", { name: "Fire timeline" });
    await clock.evaluate((el: HTMLInputElement) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(el, "900");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await expect(page.getByText(/leave at T\+07:00/i)).toBeVisible();

    expect(errors).toEqual([]);
  });
});
