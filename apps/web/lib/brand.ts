/**
 * Product name and branding — the single place to change when renaming.
 *
 * The API has a matching constant in apps/api/app/brand.py (it deploys
 * separately, so it can't import this file).
 */
export const BRAND = {
  name: "Aria",
  tagline: "Pre-incident world models for first responders",
  description:
    "Fire pre-plans for Los Angeles first responders: how fire spreads through a building, which exits stay open, and how long it takes to clear.",
} as const;

/**
 * Legal owner of the software. Separate from the product name: renaming the
 * product doesn't change the owner.
 */
export const LEGAL = {
  owner: "Lincoln",
  copyrightYear: 2026,
} as const;

export const COPYRIGHT_NOTICE = `Copyright © ${LEGAL.copyrightYear} ${LEGAL.owner}. MIT License.`;
