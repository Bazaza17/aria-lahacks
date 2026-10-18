import { test, expect } from "@playwright/test";

const VENUE = process.env.NEXT_PUBLIC_VENUE_BUILDING_ID ?? "547b5ec5-30c5-4f76-8080-012a52e90bd9";

test.describe("Dashboard", () => {
  test("map, venue panel, engine pre-plan, links", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { level: 1, name: "Los Angeles" })).toBeVisible();
    await expect(page.getByText(/scanned and ready/)).toBeVisible();
    await expect(page.locator(".mapboxgl-canvas")).toBeVisible({ timeout: 30_000 });

    // Panel: the venue, its links and the engine's pre-plan (rooms, not invented headcounts).
    await expect(page.getByText("James West Alumni Center").first()).toBeVisible();
    await expect(page.getByRole("link", { name: /View building/ })).toHaveAttribute(
      "href",
      `/building/${VENUE}`,
    );
    await expect(page.getByRole("link", { name: /Live response/ }).last()).toHaveAttribute(
      "href",
      new RegExp(`/live/view`),
    );
    await expect(page.getByText(/Rooms at risk on Aria/)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(/First exit lost/)).toBeVisible();

    // The venue marker on the map opens the building's fire model.
    await page.getByRole("button", { name: /Open James West Alumni Center/ }).click();
    await expect(page).toHaveURL(new RegExp(`/building/${VENUE}`), { timeout: 30_000 });

    expect(errors).toEqual([]);
  });
});
