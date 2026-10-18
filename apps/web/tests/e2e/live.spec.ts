import { test, expect } from "@playwright/test";

// The live response console (served by the API through the web app's /live proxy). Read-only:
// these tests never declare a drill, which would text and call registered phones.
const VENUE = process.env.NEXT_PUBLIC_VENUE_BUILDING_ID ?? "547b5ec5-30c5-4f76-8080-012a52e90bd9";

test.describe("Live response console", () => {
  test("opens with no key, back links, fire start handed over", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    // Belt and braces: fail loudly if anything tries to declare or end an evacuation.
    await page.route(/\/live\/(buildings\/[^/]+\/evacuations|evacuations\/)/, (route) =>
      route.request().method() === "GET" ? route.continue() : route.abort(),
    );

    await page.goto(`/live/view?building=${VENUE}&origin=120`);

    // No login: the console itself, with the drill control and the back links.
    await expect(page.locator('input[type="password"]:visible')).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Declare/ })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("link", { name: /Fire model/ })).toHaveAttribute(
      "href",
      `/building/${VENUE}`,
    );
    await expect(page.getByRole("link", { name: "Dashboard" })).toHaveAttribute(
      "href",
      "/dashboard",
    );

    // The building page's fire start arrives preselected.
    await expect(page.getByLabel("Fire origin")).toHaveValue("120");

    // The 3D view loads the scan and the exit markers.
    await expect(page.locator("#scene canvas")).toBeVisible();
    await expect(page.getByText(/Main entrance/).first()).toBeAttached({ timeout: 30_000 });

    await page.getByRole("link", { name: /Fire model/ }).click();
    await expect(page).toHaveURL(new RegExp(`/building/${VENUE}`));

    expect(errors).toEqual([]);
  });
});
