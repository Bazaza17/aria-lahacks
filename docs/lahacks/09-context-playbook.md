# Context playbook: keeping long Claude Code sessions sharp

How the context window fills up, what `/compact` keeps and loses, and how to hand off between sessions without losing work. Facts are from the Claude Code docs (checked Oct 17, 2026; links at the bottom).

## For Claude, when this file is dropped in

1. Read it.
2. Ask Lincoln which of these he wants (AskUserQuestion, multi-select):
   - Write a handoff now (`docs/lahacks/08-handoff.md`, template below)
   - Add the "Context" block below to `CLAUDE.md`
   - Set up the compaction hook (optional section below)
   - Add `docs/lahacks/` to `.worktreeinclude` so worktree sessions get these notes
3. Do only what he picks. Then follow "Rules for Claude" for the rest of the session.

## The short version

- The context window holds the whole conversation: every message, every file Claude read and every command output. Claude gets less sharp as it fills, and Claude Code compacts it automatically near the limit.
- Compacting never touches files on disk. It replaces the conversation with a summary.
- Before any compact or session switch, get the state onto disk: decisions, a handoff note, committed code.
- Act at a natural break, not mid-task. The desktop Context panel (or `/context`) shows how close auto-compact is. Don't let auto-compact pick the moment.

## What fills the context

| What | How big | Notes |
|---|---|---|
| Messages | Usually most of it | Includes every file read, command output, log and test run, not only what you typed |
| Startup content | Small | System prompt, `CLAUDE.md`, memory, skill list, tool definitions |
| Deferred MCP tools | Names only | Full tool definitions load only when one is used, so a big tool count isn't the problem |
| Subagents and background workflows | Not in yours | They work in their own context; only their summary comes back |

## What `/compact` keeps and what it loses

**Kept or reloaded**
- Everything on disk: code, `docs/lahacks/`, git. Untouched.
- A structured summary of the conversation: your requests and intent, key technical concepts, files examined or changed (with the important snippets), errors and how they were fixed, pending tasks, and the current work.
- Reloaded automatically: system prompt, `CLAUDE.md` (project and `~/.claude/CLAUDE.md`), memory, MCP tools.
- Re-read: up to five of the most recently modified files. A file over about 5,000 tokens comes back as a path only.
- Re-injected: skills used in the session (up to 5,000 tokens each, 25,000 total; oldest dropped first).
- Output of any `SessionStart` hook with the `compact` matcher (optional section below).

**Lost**
- The exact wording of earlier messages.
- Full tool outputs: file contents, command and test output.
- Intermediate reasoning and dead ends.
- One-off details the summary didn't keep (a preference mentioned once, an exact error from hours ago).
- The list of skills Claude hasn't used yet. It doesn't reload after compaction.
- Rules from nested `CLAUDE.md` files or path-scoped rules. They come back when Claude reads files in that folder again.

## Your options

| Option | What it does | Use it when | What you lose |
|---|---|---|---|
| `/compact <focus>` | Summarizes the whole conversation, keeps going in the same session | You're mid-feature and want to continue | Verbatim history |
| `/rewind` → **Summarize up to here** | Condenses older messages, keeps recent ones word for word | Old planning is stale but the current task's details matter | Verbatim older history |
| Handoff → new session | New session starts with `CLAUDE.md`, the docs and the handoff only | Switching tasks, or the session is full of failed attempts | Everything not in the handoff (you choose what carries) |
| `/clear` | Wipes the conversation | The next task is unrelated and nothing needs carrying | The whole conversation (files stay) |

Default: between features, hand off to a new session. Mid-feature, `/compact` with a focus or `/rewind` → Summarize up to here.

## Before you compact or switch: save to disk

- [ ] Decisions are in `docs/lahacks/01-decisions.md`
- [ ] State is in `docs/lahacks/08-handoff.md` (template below)
- [ ] Code is committed
- [ ] Background tasks still running are noted, with where their results land
- [ ] Anything that only lives in the chat is written down: commands that worked, env quirks, IDs (Supabase project ref, the venue's building `id`), the scan-to-room mapping

## Copy-paste prompts

**Write a handoff** (in the old session):

> Before we switch sessions: write `docs/lahacks/08-handoff.md` using the template in `docs/lahacks/09-context-playbook.md`, and update `docs/lahacks/01-decisions.md` with any decisions I made. Keep the handoff under 10,000 characters.

**Start the new session** (Ctrl+N in the desktop app):

> Read `CLAUDE.md`, `docs/lahacks/00-start-here.md` and `docs/lahacks/08-handoff.md`, then continue with the next step in the handoff. Ask me before anything that changes scope.

Rename the old session first (`/rename`) so you can find it later.

**Compact on your terms:**

```
/compact Keep decisions, every file created or changed, the scan-to-room mapping, setup state (Supabase, Mapbox, env files), running background tasks and the next 3 steps. Drop exploration, raw tool output and failed attempts.
```

**Compact only the old part:** press Esc twice (or run `/rewind`), pick a message from before the current task, and choose **Summarize up to here**.

## Handoff template (`docs/lahacks/08-handoff.md`)

```markdown
# Handoff — <date, time>

## Goal right now
## Done
## In progress
## Files created or changed
## Decisions (also in 01-decisions.md)
## Setup state
- Supabase: project ref, migrations run, `scans` bucket, venue building id
- Mapbox: token set, map centered on the venue
- Env files: which exist (never paste the values)
## Background tasks
## Open problems and gotchas
## Next 3 steps
```

Keep it under 10,000 characters. That's the cap for hook output (below), and a short handoff actually gets read.

## Habits that keep context small

- **One session per feature.** Name it with `/rename`; come back to it from the desktop sidebar, or `claude --resume` / `claude --continue` in the terminal.
- **`/clear` between unrelated tasks.**
- **Send heavy investigation to subagents or background workflows.** Their file reading stays in their context.
- **`/btw` for side questions.** The answer never enters the conversation history.
- **Point to files instead of pasting big logs.**
- **After two failed corrections on the same problem**, stop and start fresh with a better prompt that includes what you learned.
- **Never read big or binary files raw** (GLB scans, lockfiles, long logs). Summarize them with a script, like `trimesh` bounds for a scan.

## Rules for Claude

Paste this block into `CLAUDE.md` to make it apply to every session:

```markdown
## Context
- When compacting, always preserve the list of modified files, decisions, setup state and next steps.
- When I say **"handoff"**: update `docs/lahacks/01-decisions.md`, write `docs/lahacks/08-handoff.md` from the template in `docs/lahacks/09-context-playbook.md`, then give me the first message for the new session. You can't run `/compact` or `/clear` yourself; tell me what to type.
- Keep tool output small: use head, tail, grep and quiet flags. Summarize big or binary files (scans, logs) with a script instead of reading them.
- Send broad investigation to a subagent so only its summary comes back.
```

## Optional: re-inject the handoff after every compaction

A `SessionStart` hook with the `compact` matcher runs after every compaction, manual or automatic, and Claude Code adds whatever it prints to the context. Pointing it at the handoff file means the latest state comes back every time. Add this to `.claude/settings.local.json` (personal and gitignored); if the file already has settings, merge it in rather than replacing:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "cat \"${CLAUDE_PROJECT_DIR}/docs/lahacks/08-handoff.md\""
          }
        ]
      }
    ]
  }
}
```

- Output is capped at 10,000 characters. Anything longer is saved to a file with only a 2,000-character preview, and Claude isn't told to read the file.
- On Windows the hook runs in Git Bash, which Claude Code uses when it's installed.
- The hook only helps if the handoff is current, so update it at each break.

## Worktrees

`docs/` is gitignored, so a new worktree (including a desktop-app worktree session) starts without `docs/lahacks/`. `.worktreeinclude` copies gitignored files into each new worktree. It uses `.gitignore` syntax, so add this line:

```
docs/lahacks/
```

Add `.claude/settings.local.json` on another line too if you want the hook in worktree sessions. Each worktree gets a copy made when it's created, so later edits in the main folder don't follow.

## Sources

- [Best practices: manage your session](https://code.claude.com/docs/en/best-practices.md)
- [Explore the context window: what survives compaction](https://code.claude.com/docs/en/context-window.md)
- [Hooks guide: re-inject context after compaction](https://code.claude.com/docs/en/hooks-guide.md)
- [Hooks reference: SessionStart matchers, output cap, Windows shell](https://code.claude.com/docs/en/hooks.md)
- [Worktrees: `.worktreeinclude`](https://code.claude.com/docs/en/worktrees.md)
