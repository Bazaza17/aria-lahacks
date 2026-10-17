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
    "Pre-incident plans for Miami first responders facing hurricane, surge, and flood scenarios.",
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

/** Uppercase wordmark used in the mono UI chrome (e.g. "ARIA"). */
export const BRAND_WORDMARK = BRAND.name.toUpperCase();
