# CREAO run share link: what Aayush needs to do

**Deadline: Devpost closes Sun Oct 18, 12:00 PM PDT. Do this now.**

## Why

The CREAO prize rule says: "In your Devpost README, include a share link to one of the agent's runs
and the agent ID (shown on its page)."

The README at https://github.com/Bazaza17/aria-lahacks already has all six agent IDs. The run
share link is still a placeholder (`CREAO_RUN_SHARE_LINK`). Without it, the CREAO entry can be
ruled out.

## What we need

A **public share link to one finished run of the "Aria · Incident Commander" agent**, made from
the CREAO web app while logged in as the agents' owner (Aayush).

These do **not** count:

- `https://agent.creao.ai/api/v1/apps/<id>/runs`: the API Trigger. It returns 401 for anyone.
- `https://agent.creao.ai/install/<id>`: the agent's install page, not a run.
- A 32-character id like `106592654ec9406f8b6a511318d73ee5`: Aria's own internal run id. CREAO
  doesn't know it.

## Steps

1. Log in at https://agent.creao.ai as the owner of the six "Aria · …" agents.
2. Open **Aria · Incident Commander**.
3. Before going further, note the **Agent ID shown on its page**. Check that it is
   `ef349685-a692-4a0d-ae20-eb2e1f524624`. If it's different, send Lincoln the one CREAO shows.
4. Open its **runs / history** and pick a run:
   - Ideally one from **during a drill**. Its status is done and its output ends with an
     `aria-actions` block.
   - A known recent Commander run: CREAO run id `e3b669dc-2e26-4529-a669-db8e787a160d`
     (11:02 AM). It works, but it started just after a drill ended, so a run from mid-drill is
     better if one is easy to find.
5. **Privacy check before sharing.** Read the run's **inputs**. Aria sends the snapshot to CREAO
   **unmasked**, so it may contain full phone numbers (ours from testing). If you see a full phone
   number:
   - pick another run whose inputs have none, or
   - only share it if the number's owner is OK with it being public.
6. Click **Share** on the run, or "Copy link" / "Make public". If there's no share button, copy
   the run page's URL from the browser address bar.
7. **Test the link** in a private/incognito window, logged out. It must show the run without a
   login. If it asks you to log in, the run isn't public yet: look for a "public" / "anyone with
   the link" setting.
8. **Never** show or paste the `capi_` API key or the API Trigger settings.

## Send back to Lincoln

- The share link. It starts with `https://agent.creao.ai/` and has no `/api/v1/` in it.
- That run's CREAO run id.
- Confirmation that the Agent ID on the Commander's page is `ef349685-a692-4a0d-ae20-eb2e1f524624`,
  or the correct one.

Lincoln's Claude swaps the link into `README.md`, `docs/lahacks/15-devpost.md` and
`docs/creao-layer.md`, and pushes.
