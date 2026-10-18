# Contributing

## Branching

- Commit to `main` in small steps that each leave the code working.
- Use a short-lived branch (`feat/<topic>`, `fix/<topic>`) for anything risky,
  and merge it back once it works.
- Never force-push to `main` or rewrite shared history.

## Commits

- Small, focused commits that each leave the code working.
- Imperative subject line under ~72 characters, e.g. `Add flood depth legend`.
- Use the body to explain *why* when it isn't obvious.

## Before you push

```bash
pnpm check     # lint, format check, typecheck, unit tests — same as CI
pnpm format    # auto-fix formatting if the check complains
```

Run `pnpm test:e2e` too when you change the building page (needs `pnpm dev`
running and a seeded Supabase).

## Rules of the road

- **No secrets in git.** Real values go in `apps/web/.env.local` and
  `apps/api/.env` (both ignored). When you add a variable, add it with an empty
  value to the matching `.env.example` and to the table in the README.
- **No large files.** Scans, photos and other binaries go in Supabase Storage.
  CI rejects files over 1 MB. See
  [ADR 0002](docs/decisions/0002-large-assets-outside-git.md).
- **Product name** comes from `apps/web/lib/brand.ts` / `apps/api/app/brand.py`,
  never hardcoded.
- **Significant decisions** get a short ADR in `docs/decisions/`.

## Git blame

Formatting-only commits are listed in `.git-blame-ignore-revs`. GitHub applies
it automatically; locally run once:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```
