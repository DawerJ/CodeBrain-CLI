"""CodeBrain client CLI — standalone, no private server code required.

Commands
--------
    signup      Create a new CodeBrain account (run once, on any machine).
    login       Log in to an existing account and save credentials locally.
    new         Create a new project and set up local config files.
    init        Connect a project to a CodeBrain server (power-user / non-interactive).
    up          Verify connection and check for client file updates.
    upgrade     Refresh CLAUDE.md, slash commands, and git hook to latest templates.
    ci          Scaffold a GitHub Actions workflow for automatic rescanning.
    rescan      Scan source files and push changed code units to CodeBrain (used by CI).

Quickstart (new user)
---------------------
    codebrain signup
    codebrain new

Quickstart (existing user, new project)
----------------------------------------
    codebrain login
    codebrain new
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_URL = "https://codebrain-production.up.railway.app"

# ── Template generators ───────────────────────────────────────────────────────

def _make_claude_md(name: str, codebase_id: str) -> str:
    return f"""\
# CodeBrain — {name}

codebase_id: `{codebase_id}`

CodeBrain is a persistent understanding layer for this codebase. It remembers what every
function does, tracks open questions across sessions, stores session summaries so every
conversation starts with full context, and flags code that changed since it was last understood.
It also coordinates concurrent work between developers: before you touch any code, claim it;
before you start, check if a teammate already has. You interact with it through MCP tools —
they are already wired up in `.mcp.json`.

---

## Automatic behaviors — do these without being asked

**Session start:** call `get_session_context` first. Before files, before questions, before anything.

**Before any substantive work** (non-trivial edits, new features, refactors):
1. Identify which functions AND files you intend to modify
2. `check_work_claims(function_names=[...], file_paths=[...])` — if conflicts exist, STOP and tell
   the user; do not proceed with the conflicting functions/files
3. Ensure you are on a feature branch, not master/main: `git branch --show-current`
   - If on master/main: `git checkout -b <short-descriptive-name>`
4. **Sync with main before touching code**: `git fetch origin && git rebase origin/master`
   - This prevents your branch from going stale and later rolling back a teammate's merged changes
   - If rebase has conflicts, resolve them now before starting your work
5. `claim_work(function_names=[...], file_paths=[...], description="...", branch_name="...", contracts={{...}})`
   - Always include `file_paths` — two devs editing different functions in the same file can still
     create a git rollback if their branches diverge. File-level claims surface this conflict early.
   - `contracts`: for each function you DEPEND ON but won't modify, write what you need from it
   - Example: `{{"authenticate_user": "must return {{id, username, role}} or None — do not change shape"}}`
6. Store the returned `claim_id` — you'll need it for heartbeats and release

**During work:**
- Call `report_change` after every edit
- Call `flag_unknown` when you hit something uncertain
- Call `heartbeat_work_claim(claim_id)` roughly every hour in a long session
- **For every function you read deeply or modify**: call `push_learn_content` with what it does,
  how it works (pseudocode / code flow), key concepts it embodies, and any gotchas. This is the
  primary way CodeBrain builds understanding — don't skip it.
- **Add `@feature:` to every docstring you write or modify.** Untagged functions are invisible
  to the architecture diagram and the Last Session review page.

**Session end (in order):**
1. `push_session_summary` — write what changed, decisions, discoveries, open questions
2. `release_work(claim_id)` — free the functions for teammates

Shortcuts: `/project:session-start` at the top, `/project:session-end` at the bottom.

---

## Knowledge is the primary output

The code you write will be refactored, deleted, and replaced. The knowledge CodeBrain captures — what functions do, how concepts connect, what this developer understands — compounds permanently. Every session should leave CodeBrain measurably smarter. **That is the job.**

**Three layers, all mandatory:**

**Layer 1 — Knowledge about code** (`push_learn_content`, `push_module_context`, `add_annotation`)

For every function you read deeply or modify, write learn content as if training a developer who will own this code for years. Quality bar — each field matters:
- `explanation`: the WHY (design decision, trade-off) + WHAT it does in plain English. Start with motivation, not mechanics.
- `code_flow`: numbered steps — `"1. validate input → 2. look up user → 3. compare hash → 4. issue token"`
- `key_concepts`: what broader knowledge is required to understand or safely change this function
- `gotchas`: what would trip up someone new — the non-obvious parts, the hidden constraints, the traps

❌ Weak: `explanation="Authenticates the user."`
✓ Strong: `explanation="Verifies credentials using PBKDF2-HMAC-SHA256 with timing-safe comparison, then issues a JWT. Returns None on failure rather than raising — callers must check the return value."` `code_flow="1. look up user by username → 2. if not found return None immediately → 3. hmac.compare_digest → 4. generate JWT with 24h expiry"` `gotchas=["hmac.compare_digest is essential — == leaks timing info", "Returns None not raises — callers MUST check return value or auth is silently bypassed"]`

Annotations should capture what isn't in the code: constraints that can't be seen from reading, invariants discovered via incidents, decisions made for non-obvious reasons.

**Layer 2 — Knowledge about concepts** (`push_concept_graph`, `suggest_concept`, `mark_concepts_universal`)

- When you explain something to the user, that explanation IS knowledge — capture it in `push_learn_content` or `push_concept_graph`. Don't let it disappear into the chat log.
- **This applies to product and workflow knowledge too.** If you explain how the system works end-to-end — its loops, its lifecycle, its architecture — that belongs in `push_concept_graph`, not just in the chat. The concept graph is what `get_jit_context` draws from; if the workflows aren't in it, JIT can never teach them.
- When a concept comes up, ask: is this in the graph? Does it have the right edges?
- Connect functions to the concepts they embody — push those as concept edges
- Suggest concepts that aren't in the graph yet. Promote to universal when applicable.

**Layer 3 — Knowledge about the human** (mastery signals, throughout the session)

- Every function you explain is a mastery data point. Every concept the user skips, every question they ask — these are signals. Treat them as data.
- At session end, reflect what you observed before asking for feedback: *"You engaged deeply with X and seemed confident with Y, but we moved quickly past Z — does that match?"*
- The user's self-assessment calibrates the passive model. It's the most accurate signal in the system.

**The session is not complete when the feature is done. It is complete when the knowledge is recorded.**

---

**Proactively suggest session end — watch for these signals and offer without waiting:**
- Feature, fix, or PR is complete → "We just wrapped [X]. Good stopping point — want me to run `/project:session-end`?"
- Blocker hit that requires waiting on a teammate, external service, or a decision you can't make → suggest ending and returning
- User pivots to a clearly different scope → "This sounds like a new topic. Want to end this session and start fresh?"
- Work claim held > 2 hours with no recent progress → "We've had [functions] claimed for a while. Should we wrap up or heartbeat the claim?"
- Context feels heavy (many files read, many decisions, long history) → mention at a natural pause

Do not wait for the user to think of this. They're focused on the work. You manage session hygiene.
After a session ends: "Start the next session with `/project:session-start` when you're ready."

**JIT teaching — MANDATORY gate before any work begins:**
The moment the user describes what they want to work on, call `get_jit_context` immediately —
before checking code, before forming a plan, before anything else.
`get_jit_context(description="<their exact words>", codebase_id="{codebase_id}")`
**Hard stop:** if you are about to touch code or make a decision and have NOT called it this session — stop and call it now.
This is not optional. JIT is the delivery mechanism that turns stored mastery into actual teaching.
Without it, all mastery tracking is data that never reaches the developer.
If response shows unknown or low mastery: offer in one sentence: "Want a quick orientation on [X, Y] before we dive in? (yes / skip)"
If yes: `get_concept_details`, calibration questions one at a time, mental model first, code only if requested.
If skip: proceed without follow-up, never mention it again this session.
If all concepts show solid mastery: proceed without offering.

**Quality bar — never skip for these reasons:**
❌ "The task seems obvious" — the mastery model knows better than you do
❌ "The user built this system" — irrelevant; offer and let them skip
❌ Offering on something the user demonstrated fluency on this session

**Before delivering any JIT explanation:**
Call `evaluate_jit_explanation(explanation="<draft>", concept_names=[...], mastery_levels={{...}})`.
Pass the `mastery_levels` dict directly from `get_jit_context` output.
If score < 70 or pass=false: revise using the feedback and call again. Maximum two revision attempts.
Do not deliver until it passes. Every call is logged automatically for dataset building.

**Concept suggestions — during any session:**
If a concept, pattern, or idea comes up in conversation that seems like it should be in
the concept graph but isn't (get_jit_context returned no match, or you recognize a gap),
call `suggest_concept(name="...", description_hint="...", context="...", codebase_id="{codebase_id}")`.
Do this silently — no need to announce it. The owner reviews the queue daily in the web UI
(Build → Annotate → Concept Review Queue) and adds the ones that belong.

**Teaching delivery — how to explain anything to the user:**
Whether delivering JIT orientation, answering a question, or explaining a system, always scaffold:
- Start with ONE core mental model. Deliver it. Pause. Check understanding before adding the next layer.
- Never deliver more than ~4 new concepts at once — this is a working memory limit, not a style preference.
- Even if the user asks for "all of it," start with the smallest useful chunk and build up incrementally.
- "Continue" or "yes" from the user = confirmation to advance exactly one layer, not permission to dump everything.
- The right answer to "explain the whole system" is one sentence, then a question.

---

## Before editing any function

Call `get_function_context` to see annotations, risk findings, known callers (blast radius),
and any constraints previous sessions or teammates recorded. Non-optional for CRITICAL/STANDARD functions.

```
get_function_context(function_name="FUNCTION_NAME", codebase_id="{codebase_id}")
```

---

## While writing code — docstring tags

Add these to function docstrings. They are parsed at ingestion at zero LLM cost and
automatically create annotations, feature assignments, and dependency edges.
**Always update docstring tags when you change a function** — CI re-parses them on every push,
so keeping them current means CodeBrain stays accurate for free.

```python
def my_function():
    \"\"\"
    Short summary.

    @feature: Feature Name         # which feature this belongs to
    @depends: other_fn, helper_fn  # direct function dependencies
    @note: a constraint or gotcha  # warning for future readers (repeatable)
    @decision: why this approach   # design rationale
    @reads: table_name             # external state this reads (repeatable)
    @mutates: table_name           # state this modifies (repeatable)
    @auth-required: description    # what auth must hold before calling
    @failure-mode: what breaks     # what happens when this fails (repeatable)
    @unknown: open question        # known unknown to investigate (repeatable)
    \"\"\"
```

All tags: `@feature` `@concept` `@depends` `@note` `@decision` `@tradeoff`
`@reads` `@mutates` `@emits` `@auth-required` `@pii` `@trust-boundary`
`@failure-mode` `@unknown` `@deprecated` `@idempotent` `@sla` `@criticality`

---

## After changes

```
report_change(
    function_names=["fn_a", "fn_b"],
    summary="one sentence: what changed and why",
    codebase_id="{codebase_id}"
)
```

---

## End of session

```
push_session_summary(
    what_done="bullet list of what was changed or decided",
    open_questions=["anything still unresolved"],
    discoveries=["invariants found", "gotchas uncovered"],
    lessons_learned=["patterns that worked", "things to avoid"],
    codebase_id="{codebase_id}"
)
# Then immediately:
release_work(claim_id="<your-claim-id>", codebase_id="{codebase_id}")
```

---

## Connecting the dots — do this continuously, not just at evaluation time

These tools build CodeBrain's knowledge. Use them throughout the session whenever
you have context to share — you have better understanding than any automated pipeline.

| Tool | When to call it |
|------|----------------|
| `push_learn_content` | After reading or modifying any function — explain what it does, how it works, gotchas |
| `set_feature_mapping` | Whenever you can confidently assign functions to features (even just a few at a time) |
| `update_architecture_doc` | After forming or revising your mental model of the system |
| `push_concept_graph` | After identifying how key concepts relate to each other |
| `push_module_context` | After understanding a file's role, invariants, and boundaries |

**The feature assignment gap problem:** If `get_session_context` reports many unassigned
functions, that means the architecture diagram and Last Session page are working blind.
Assign what you can. Even partial coverage makes the tools dramatically more useful.

---

## Quick reference

| Moment | Tool |
|--------|------|
| Session start | `get_session_context("{codebase_id}")` |
| Check before working | `check_work_claims(function_names=[...])` |
| Stake your claim | `claim_work(function_names=[...], description=..., branch_name=..., contracts={{...}})` |
| Before editing | `get_function_context(function_name=..., codebase_id="{codebase_id}")` |
| After changes | `report_change(changed_functions=[...], summary=..., codebase_id="{codebase_id}")` |
| Keep claim alive | `heartbeat_work_claim(claim_id=...)` |
| Found unknown | `flag_unknown(question=..., function_name=..., codebase_id="{codebase_id}")` |
| Session end | `push_session_summary(...)` then `release_work(claim_id=...)` |
| Search | `search_functions(query=..., codebase_id="{codebase_id}")` |
"""


def _make_session_start_md(codebase_id: str) -> str:
    return f"""\
Run `codebrain up` now (before anything else) to check for client updates.
If it prints warnings about stale files or a version mismatch, run `codebrain upgrade` to
refresh them, then restart Claude Code so the new instructions take effect.

Then call the `get_session_context` MCP tool now with codebase_id="{codebase_id}".

Do not ask for permission. Do not wait. Call it immediately after the update check.

After the tool returns, report:
- Architecture summary (2-3 sentences)
- Active work claims from teammates (who is working on what, on which branch)
- Any open unknowns that need attention
- Staleness summary (what artifacts need regeneration)
- What the last session did (for continuity)

## First-run checks — do these immediately after get_session_context

**Check 1: Is the codebase indexed?**
Look at `total_functions` in the get_session_context response.
If `total_functions == 0`, the codebase has never been scanned. Tell the user:
  "No functions are indexed yet. Running initial scan now..."
Then call `rescan_stale(codebase_id="{codebase_id}")` — it will auto-detect all Python files
and do a full initial scan. Report how many functions were found.
If it reports nothing found, tell the user to add .py files to their project first,
then re-run `/project:session-start`.

**Check 2: Is this a git repository?**
Run: `git rev-parse --is-inside-work-tree 2>/dev/null && echo yes || echo no`
If the output is NOT "yes", warn the user with this message (verbatim):

  ⚠️  **No git repository detected.**

  CodeBrain works best with git. Without it:
  - Staleness detection relies only on file-hash polling — changes won't be caught
    automatically between sessions, so CodeBrain's understanding will drift.
  - The rescan CI action (which keeps context fresh on every push) won't work.
  - Work claims and branch coordination have no foundation.
  - `git blame`, change-frequency metrics, and hotspot detection are disabled.

  **Recommended:** Run `git init && git add -A && git commit -m "initial commit"`
  now, then push to GitHub and add the CodeBrain CI action (`codebrain ci`).
  This is a one-time setup that pays off every session.

  You can continue without git, but expect context drift over time.

**Check 3: Is the branch up to date?**
Run these git checks and report the results:
1. `git branch --show-current` — what branch are we on?
2. `git fetch origin --quiet && git status -sb` — is this branch behind origin/master?

If the branch is behind origin/master, STOP and tell the user:
  "Your branch is N commits behind origin/master. A teammate has merged changes since you
   last synced. Run `git rebase origin/master` before we start, so your work doesn't
   accidentally roll back their changes when you push."
(Skip this check if there is no git remote — `git fetch` will error, that's fine.)

Then ask the user what they want to work on today.

## JIT teaching — MANDATORY gate before any work begins

`get_jit_context` is not optional. It is the delivery mechanism that converts stored mastery
knowledge into actual teaching — without it, every `push_learn_content` and mastery signal from
prior sessions is data that never reaches the developer. JIT is the whole point of tracking mastery.

**Rule: the moment the user describes what they want to work on, call get_jit_context immediately —
before checking code, before forming a plan, before anything else.**

  `get_jit_context(description="<their exact words>", codebase_id="{codebase_id}")`

**Hard stop:** If you find yourself about to touch code or make a decision and have NOT called
`get_jit_context` this session — stop and call it now.

**If the tool returns unknown or low mastery concepts**, offer in exactly one sentence:
  "Want a quick orientation on [concept A, concept B] before we dive in? (yes / skip)"

If the user says **yes**:
1. Call `get_concept_details(concept_names=[...], codebase_id="{codebase_id}")` for the unknown/low concepts
2. For each concept with unknown mastery, ask the suggested calibration question first (one at a time),
   then tailor depth to what the answer reveals
3. Lead with the mental model. Add code only if requested.
4. After explaining, ask if they want to drill to actual code before proceeding.

If the user says **skip** (or does not engage), proceed without follow-up — never bring it up again.

If get_jit_context returns solid mastery on all matched concepts, proceed without offering.

**Quality bar:**
❌ Skipping because the task "seems obvious" — the mastery model knows better than you do
❌ Offering on something the user just demonstrated they know fluently
✓ One sentence, specific concept names, binary yes/skip — never more than 15 words
✓ Always fires on every new goal description, even mid-session pivots

Throughout the session: if any concept, pattern, or idea comes up that isn't in the concept
graph, call `suggest_concept(name="...", description_hint="...", context="...", codebase_id="{codebase_id}")` silently.
The owner reviews the queue daily in Build → Annotate → Concept Review Queue.

IMPORTANT: Before starting any substantive work this session:
1. check_work_claims(function_names=[...], file_paths=[...]) on everything you plan to touch
2. Switch to a feature branch if on master/main
3. Rebase on master if the branch is stale: git fetch origin && git rebase origin/master
4. claim_work(function_names=[...], file_paths=[...], ...) — always include file_paths

## Session lifecycle — proactively manage this throughout the session

Watch for these signals and offer to end the session without waiting for the user to ask:

| Signal | What to say |
|--------|------------|
| Feature / fix / PR is done | "We just wrapped [X]. Good stopping point — run `/project:session-end`?" |
| Blocker requiring external input | "We're blocked waiting on [X]. Good time to end and return when it's resolved." |
| User pivots to unrelated scope | "This sounds like a new topic. Want to end this session first?" |
| Work claim held > 2h with no progress | "We've held [functions] claimed for a while — heartbeat or wrap up?" |
| Context feels heavy | Mention at a natural pause: "We've covered a lot — fresh session after this might help." |

After session end, always say: "Start the next session with `/project:session-start` when ready."
"""


def _make_session_end_md(codebase_id: str) -> str:
    return f"""\
This session is ending. Execute these steps in order — do not skip any:

0. **Knowledge sweep — do this before anything else:**

   For every function you touched or read deeply this session, confirm you've called `push_learn_content`.
   This is not optional. The session summary records what changed; push_learn_content is what teaches
   the next developer (or next Claude) how things actually work.

   If you skipped any during the session, write them now. Each should have:
   - `explanation`: WHY this function exists + what it does — start with motivation, not mechanics
   - `code_flow`: numbered step-by-step execution path
   - `key_concepts`: what you need to understand to safely change this
   - `gotchas`: what would trip up someone new — hidden constraints, non-obvious traps

   Also: if any concepts came up this session that aren't yet in the concept graph, call `suggest_concept`
   or `push_concept_graph` now. Don't let that understanding disappear into the chat log.

1. Call `push_session_summary` with codebase_id="{codebase_id}":

   **Required:**
   - `what_done`: 2-4 plain-language sentences describing what changed and why —
     write it so a teammate who wasn't in this session can understand the motivation.

   **Structured fields (power the Last Session review page — fill these carefully):**
   - `features_touched`: list of feature names touched, e.g. ["Journey", "Drill", "API"]
   - `functions_changed`: list of dicts for every function/file you changed:
       {{"name": "function_name", "file": "path/to/file.py", "why": "one sentence — what problem this change solves"}}
     Include files too if the change was structural (not just a single function).
   - `notable`: list of things worth reviewing or understanding — subtle invariants,
     risky decisions, places that could break, things a reviewer should look at closely.

   **Optional:**
   - `open_questions`: anything still unresolved or uncertain
   - `discoveries`: non-obvious things you learned about the codebase
   - `lessons_learned`: what would have been useful to know at the start

2. **Mastery reflection — always do this, even if push_session_summary shows no changes:**

   First, reflect aloud on what you observed this session before asking the user anything:
     *"Based on what we worked on: [your observation — e.g. 'you navigated X confidently,
      explained Y clearly to me, but we moved fast through Z without diving deep'].
      Does that match how it felt?"*

   Then, if push_session_summary returned mastery changes, show them. Explain the rubric once:
     "0–30% = unfamiliar, 30–45% = aware, 45–65% = working familiarity (passive ceiling from
      session work), >65% = solid (requires drill to reach)."

   For each concept the user comments on, call:
   `record_mastery_feedback(concept_name=..., agreement="agree"|"disagree"|"partial",
    user_comment="<their words verbatim>", session_context="<brief what they worked on>",
    codebase_id="{codebase_id}")`

   The user's self-assessment is the most accurate signal in the system. Their exact words matter —
   don't paraphrase. Tell them: "I'm storing this to improve how I read what you know over time."

3. Call `release_work(claim_id="<your-claim-id>", codebase_id="{codebase_id}")` to free
   your claimed functions for teammates. If you don't have a claim_id (read-only session),
   skip this step.

Do not skip any step even if the session was short or nothing changed.
The session summary is how your teammate's Claude learns what you did,
and the Last Session page uses `functions_changed` to scope the code review.
"""


def _make_explore_md(codebase_id: str) -> str:
    return f"""\
Call `get_architecture(codebase_id="{codebase_id}")` immediately. Do not ask for permission.

Then deliver a codebase orientation in this order:

**1. The system in one sentence**
Summarize what this codebase does and why it exists. Start with the problem it solves, not the tech stack.

**2. The three layers (always include this)**
Explain CodeBrain's knowledge model briefly:
- Layer 1 — Code knowledge: what every function does, how it works, what would trip someone up
- Layer 2 — Concept knowledge: a graph of concepts with edges showing what depends on what
- Layer 3 — Human knowledge: per-developer mastery estimates, silently updated from session behavior
This is the flywheel. Every session leaves CodeBrain smarter than before.

**3. Features / major subsystems**
List each feature from the architecture response. For each one, one sentence on what it does and where its boundaries are. If the architecture response has no features listed, say so and suggest running `codebrain rescan` to populate them.

**4. Key invariants**
Pull the invariants section from the architecture doc verbatim if present. These are the load-bearing rules — violating them silently corrupts behavior.

**5. What's stale or unknown**
Call `get_session_context(codebase_id="{codebase_id}")` in parallel with get_architecture if you haven't already this session, and surface:
- Stale function count (if > 0: "N functions changed since last understood — run `codebrain rescan`")
- Open unknowns count (if > 0: "N open unknowns — things previous sessions flagged but left unresolved")

End with one of these, based on context:
- If stale_count > 0: "Your codebase has drifted — run `codebrain rescan` before diving in, or tell me what you're working on and we'll go from there."
- Otherwise: "Tell me what you're working on today, or say `investigate [question]` to trace a specific problem."
"""


def _make_annotate_md(codebase_id: str) -> str:
    return f"""\
This command captures a design note, warning, decision, or TODO and attaches it to a specific function or the codebase — so it lives with the code, not in a ticket or a chat thread.

## If the user ran `/project:annotate` with no arguments

Ask in a single message (all at once, not one question at a time):
1. What function or file should this be attached to? (Leave blank for codebase-level)
2. What's the annotation? (Paste or describe it — you can help draft if they're not sure)
3. What type is it?
   - `warning` — something that will break if a future dev isn't careful
   - `todo` — work that needs doing
   - `note` — useful context, not urgent
   - `decision` — why a specific approach was chosen
   - `constraint` — a hard rule that must not be violated
4. Priority: `normal` or `high`

## If the user ran `/project:annotate` with a description or context

Use what they provided to infer as much as possible. If the function name is clear from context (e.g. they were just discussing a function), pre-fill it. Ask only for what's missing.

## Drafting help

If the user says "help me write it" or provides a rough idea, draft an annotation body using this quality bar:
- Specific: names the exact constraint, risk, or decision — not "this is complex"
- Actionable: a future reader knows what to do (or not do) with this information
- Durable: will still make sense in 6 months when the context is gone

Good: "Rate limiter uses a sliding window keyed on user_id + endpoint. If you add a new endpoint, you MUST add it to RATE_LIMIT_CONFIG or it will be unthrottled by default — no error, just silent unlimited access."
Bad: "Be careful with rate limiting here."

## After collecting all inputs

Call:
```
add_annotation(
    body="<annotation text>",
    codebase_id="{codebase_id}",
    function_name="<function name or blank for codebase-level>",
    intent_type="<warning|todo|note|decision|constraint>",
    priority="<normal|high>"
)
```

Confirm: "Saved. This annotation will appear in get_function_context for [function] in every future session — yours and any teammate's."

If the annotation reveals an open question that can't be resolved now, also call:
```
flag_unknown(question="<the open question>", function_name="<function>", codebase_id="{codebase_id}")
```
"""


def _make_investigate_md(codebase_id: str) -> str:
    return f"""\
Use this command to trace a problem, answer a "how does X work" question, or understand the blast radius of a change — before touching code.

## Input

The user will either:
- Run `/project:investigate <description>` — use the description as-is
- Run `/project:investigate` with no args — ask "What do you want to investigate?" before proceeding

## Step 1 — JIT gate (mandatory, run first)

Call immediately:
```
get_jit_context(description="<their description>", codebase_id="{codebase_id}")
```

If it returns unknown or low mastery concepts relevant to the investigation, offer in one sentence:
"Want a quick orientation on [X] before we trace this? (yes / skip)"

If yes: explain the concept, check understanding, then continue.
If skip or solid mastery: proceed immediately.

## Step 2 — Find the relevant code

Call in parallel:
```
search_functions(query="<their description>", codebase_id="{codebase_id}")
get_architecture(codebase_id="{codebase_id}")
```

From the results, identify the 2-5 most relevant functions. Explain briefly why each is relevant — one sentence per function.

## Step 3 — Go deep on each relevant function

For each function identified in Step 2, call:
```
get_function_context(function_name="<name>", codebase_id="{codebase_id}")
```

These calls can run in parallel. Read the annotations, risk findings, callers, and constraints returned.

Then synthesize across all functions:
- **What's happening**: a plain-English explanation of the flow — numbered steps if useful
- **What's risky**: annotations or risk findings that are relevant to the investigation
- **What's unknown**: anything get_function_context flagged as uncertain, or that you can't explain confidently from what you've seen
- **Blast radius** (if the user is thinking about changing something): which callers would be affected, what contracts would need to hold

## Step 4 — Capture what you learned

If the investigation revealed anything non-obvious (a hidden constraint, a surprising dependency, an implicit assumption), offer:
"Want to annotate [function] with what we just found? (yes / skip)"

If yes: run `/project:annotate` inline — don't make the user switch commands.

If there are open questions that can't be resolved now, call:
```
flag_unknown(question="<the open question>", function_name="<most relevant function>", codebase_id="{codebase_id}")
```

## Step 5 — Close the loop

End with one of:
- If the user now wants to make a change: "Ready to work on this — I'll run `check_work_claims` and `claim_work` before we touch anything."
- If the investigation answered the question: "Investigation complete. Anything else to trace, or ready to start building?"
- If blocked by unknown: "We've hit a limit on what we can know without running it. Flag it or continue with what we have?"
"""


def _make_commands_md(codebase_id: str) -> str:
    return """\
List all available CodeBrain slash commands for this project. No tool calls needed — just print this reference card.

---

## Session commands

| Command | What it does |
|---------|-------------|
| `/project:session-start` | Start a session: load context, git checks, JIT teaching gate |
| `/project:session-end` | End a session: knowledge sweep, summary, mastery reflection, release work |

## Mid-session commands

| Command | What it does |
|---------|-------------|
| `/project:explore` | Codebase orientation: architecture, three-layer model, features, invariants, staleness |
| `/project:annotate [description]` | Capture a design note, warning, decision, or TODO — attached to a function, not a ticket |
| `/project:investigate [question]` | Trace a problem or "how does X work?" before touching code |

## Other

| Command | What it does |
|---------|-------------|
| `/project:check-reports` | Review open user feedback reports from production |
| `/project:commands` | Show this reference card |

---

**When to reach for each one:**
- Starting or ending work → `session-start` / `session-end`
- New to this area of the codebase → `explore`
- Something feels wrong or surprising → `investigate`
- You just made a decision, found a gotcha, or want to leave a note → `annotate`
- You forget what's available → `commands`
"""


# ── Global ~/.claude/CLAUDE.md ────────────────────────────────────────────────

def _make_global_claude_md_section() -> str:
    return """\
## CodeBrain

This user has CodeBrain installed — a persistent understanding layer that tracks what developers know and delivers JIT context during coding sessions.

**At the start of any conversation**, check whether this project is connected to CodeBrain:
- Look for a `.codebrain` file or a `CLAUDE.md` containing `codebase_id` in the current directory.
- If found: follow the local `CLAUDE.md` instructions.
- If NOT found: say this once, then help normally:
  "This project isn't connected to CodeBrain yet. Run `codebrain new` in this folder to set it up — takes about 2 minutes and gives you architecture tracking, session memory, and JIT teaching."

Don't repeat this if the user continues without setting it up."""


def _write_global_claude_md() -> bool:
    """Write (or update) the CodeBrain awareness block in ~/.claude/CLAUDE.md.
    Uses HTML markers to preserve any existing user content. Returns True if file was written."""
    import re as _re
    global_dir = Path.home() / ".claude"
    global_dir.mkdir(parents=True, exist_ok=True)
    target = global_dir / "CLAUDE.md"

    START = "<!-- codebrain:start -->"
    END = "<!-- codebrain:end -->"
    block = f"{START}\n{_make_global_claude_md_section()}\n{END}"

    if not target.exists():
        target.write_text(block + "\n", encoding="utf-8")
        return True

    existing = target.read_text(encoding="utf-8")
    if START in existing:
        new_content = _re.sub(
            f"{_re.escape(START)}.*?{_re.escape(END)}",
            block,
            existing,
            flags=_re.DOTALL,
        )
    else:
        new_content = existing.rstrip() + "\n\n" + block + "\n"

    if new_content == existing:
        return False
    target.write_text(new_content, encoding="utf-8")
    return True


# ── .mcp.json generators ──────────────────────────────────────────────────────

def _make_mcp_json(url: str, api_key: str, python_path: str | None = None) -> dict:
    """Generate .mcp.json with explicit Python path for reliable Electron launch.

    Uses sys.executable by default so Claude Code bypasses PATH resolution entirely —
    avoids the Electron partial-PATH problem where 'codebrain' isn't findable.
    """
    cmd = python_path if python_path is not None else sys.executable
    return {
        "mcpServers": {
            "codebrain": {
                "command": cmd,
                "args": ["-m", "codebrain", "mcp"],
                "env": {
                    "CODEBRAIN_URL": url,
                    "CODEBRAIN_API_KEY": api_key,
                },
            }
        }
    }


def _make_mcp_json_template(url: str) -> str:
    """Template teammates fill in — URL is pre-filled, they supply their Python path + API key."""
    lines = [
        "{",
        '  "mcpServers": {',
        '    "codebrain": {',
        '      "command": "<path-to-your-python>",  // run: python -c "import sys; print(sys.executable)"',
        '      "args": ["-m", "codebrain", "mcp"],',
        '      "env": {',
        f'        "CODEBRAIN_URL": "{url}",',
        '        "CODEBRAIN_API_KEY": "<your-api-key>"  // get from webapp: Settings -> API Key',
        "      }",
        "    }",
        "  }",
        "}",
    ]
    return "\n".join(lines) + "\n"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_gitignore(entry: str, root: Path | None = None) -> None:
    gi = (root or Path(".")) / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if entry not in existing.splitlines():
        with gi.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"{entry}\n")
        print(f"  Added '{entry}' to .gitignore")


def _ensure_gitignore_in(root: Path, entry: str) -> None:
    _ensure_gitignore(entry, root)


def _install_git_hook_in(root: Path) -> None:
    import subprocess, stat
    hooks_dir = root / ".git-hooks"
    if not hooks_dir.exists():
        return
    hook_file = hooks_dir / "pre-push"
    if not hook_file.exists():
        return
    try:
        subprocess.run(
            ["git", "-C", str(root), "config", "core.hooksPath", ".git-hooks"],
            check=True, capture_output=True,
        )
        current = hook_file.stat().st_mode
        hook_file.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print("  Installed git hook: .git-hooks/pre-push")
    except Exception as e:
        print(f"  Warning: could not install git hook: {e}")


def _install_git_hook() -> None:
    """Point git's hooksPath to .git-hooks/ so the pre-push safety hook runs."""
    import subprocess, stat
    hooks_dir = Path(".git-hooks")
    if not hooks_dir.exists():
        return
    hook_file = hooks_dir / "pre-push"
    if not hook_file.exists():
        return
    try:
        subprocess.run(
            ["git", "config", "core.hooksPath", ".git-hooks"],
            check=True, capture_output=True,
        )
        current = hook_file.stat().st_mode
        hook_file.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print("  Installed git hook: .git-hooks/pre-push")
    except Exception as e:
        print(f"  Warning: could not install git hook: {e}")


def _show_changelog(url: str, since: str = "", limit: int = 5) -> None:
    """Fetch and print recent changelog entries from the server."""
    if not url:
        return
    try:
        import httpx
        params = {"since": since} if since else {}
        r = httpx.get(f"{url}/api/v1/changelog", params=params, timeout=10)
        r.raise_for_status()
        entries = r.json()[:limit]
        if not entries:
            return
        print("\nWhat's new in this update:")
        for e in entries:
            print(f"\n  [{e['date']}] {e['title']}")
            desc = e.get("description", "")
            words = desc.split()
            line = "    "
            for word in words:
                if len(line) + len(word) + 1 > 76:
                    print(line)
                    line = "    " + word
                else:
                    line = (line + " " + word).lstrip() if line == "    " else line + " " + word
            if line.strip():
                print(line)
        print()
    except Exception:
        pass


def _fetch_template(url: str, api_key: str, template_name: str, codebase_id: str, codebase_name: str) -> str:
    """Fetch canonical template from server; fall back to local generation."""
    if url and api_key:
        try:
            import httpx
            r = httpx.get(
                f"{url}/api/v1/client-template",
                params={"template": template_name, "codebase_id": codebase_id, "codebase_name": codebase_name},
                headers={"X-API-Key": api_key},
                timeout=10,
            )
            r.raise_for_status()
            return r.text
        except Exception:
            pass
    if template_name == "session-start.md":
        return _make_session_start_md(codebase_id)
    if template_name == "session-end.md":
        return _make_session_end_md(codebase_id)
    if template_name == "explore.md":
        return _make_explore_md(codebase_id)
    if template_name == "annotate.md":
        return _make_annotate_md(codebase_id)
    if template_name == "investigate.md":
        return _make_investigate_md(codebase_id)
    if template_name == "commands.md":
        return _make_commands_md(codebase_id)
    return _make_claude_md(codebase_name or "project", codebase_id)


def _check_client_files_up_to_date(codebase_id: str, codebase_name: str, url: str, api_key: str) -> None:
    """Print a warning for any client file that differs from the server's canonical template."""
    name = codebase_name or Path.cwd().name
    checks = [
        (Path("CLAUDE.md"), _fetch_template(url, api_key, "CLAUDE.md", codebase_id, name)),
        (Path(".claude") / "commands" / "session-start.md", _fetch_template(url, api_key, "session-start.md", codebase_id, name)),
        (Path(".claude") / "commands" / "session-end.md", _fetch_template(url, api_key, "session-end.md", codebase_id, name)),
        (Path(".claude") / "commands" / "explore.md", _fetch_template(url, api_key, "explore.md", codebase_id, name)),
        (Path(".claude") / "commands" / "annotate.md", _fetch_template(url, api_key, "annotate.md", codebase_id, name)),
        (Path(".claude") / "commands" / "investigate.md", _fetch_template(url, api_key, "investigate.md", codebase_id, name)),
        (Path(".claude") / "commands" / "commands.md", _fetch_template(url, api_key, "commands.md", codebase_id, name)),
    ]
    stale = [str(p) for p, canonical in checks if not p.exists() or p.read_text(encoding="utf-8") != canonical]
    if stale:
        print("\n⚠️  Client files are behind the current template:")
        for f in stale:
            print(f"     {f}")
        print("   Run: codebrain upgrade  to refresh them")
        _show_changelog(url)


# ── Lightweight scanner (stdlib only — no codeownership dependency) ───────────

def _scan_python_files(path: str) -> list[dict]:
    """
    Scan Python files under `path` and extract function metadata using only stdlib.
    Returns a list of dicts suitable for POST /api/v1/code-units.
    """
    import ast
    import hashlib

    units = []
    for py_file in Path(path).rglob("*.py"):
        # Skip hidden dirs and common noise
        if any(part.startswith(".") or part in ("__pycache__", "node_modules", ".venv", "venv")
               for part in py_file.parts):
            continue
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(py_file))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fn_src = ast.get_source_segment(src, node) or ""
            fn_hash = hashlib.sha256(fn_src.encode()).hexdigest()[:16]
            units.append({
                "name": node.name,
                "file_path": str(py_file),
                "source": fn_src,
                "source_hash": fn_hash,
                "cyclomatic_complexity": 1,
                "criticality_score": 0.5,
                "profile_name": "STANDARD",
            })
    return units


def _run_scan_and_push(path: str, url: str, api_key: str, codebase_id: str) -> None:
    """Scan local Python files and push code units to the CodeBrain API."""
    import httpx

    units = _scan_python_files(path)
    print(f"  Found {len(units)} functions")

    total_pushed = 0
    for i in range(0, len(units), 50):
        batch = units[i:i + 50]
        r = httpx.post(
            f"{url}/api/v1/code-units",
            json={"codebase_id": codebase_id, "units": batch},
            headers={"X-API-Key": api_key},
            timeout=60,
        )
        r.raise_for_status()
        result = r.json()
        total_pushed += result.get("updated", 0) + result.get("inserted", 0)

    print(f"  Pushed {total_pushed} code units to API")


# ── CI workflow template ──────────────────────────────────────────────────────

def _make_ci_workflow(codebase_id: str) -> str:
    return f"""\
name: CodeBrain rescan on push

on:
  push:
    branches: [main, master]
    paths: ['**.py']

jobs:
  rescan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install CodeBrain client
        run: pip install git+https://github.com/DawerJ/CodeBrain-CLI.git

      - name: Rescan and push to CodeBrain
        env:
          CODEBRAIN_URL: ${{{{ secrets.CODEBRAIN_URL }}}}
          CODEBRAIN_API_KEY: ${{{{ secrets.CODEBRAIN_API_KEY }}}}
          CODEBRAIN_CODEBASE_ID: {codebase_id}
        run: codebrain rescan --path .
"""


# ── Commands ──────────────────────────────────────────────────────────────────

def _prompt(label: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"{label}{hint}: ").strip()
        return val or default
    except EOFError:
        if default:
            return default
        print(
            f"\nError: cannot prompt for '{label}' — stdin is not a TTY.\n"
            "Run this command directly in a terminal, or pass values as flags "
            "(e.g. --username, --password)."
        )
        raise SystemExit(1)


def _prompt_optional(label: str) -> str:
    """Prompt for a truly optional value; silently returns '' when stdin is not a TTY."""
    import sys
    if not sys.stdin.isatty():
        return ""
    try:
        return input(f"{label}: ").strip()
    except EOFError:
        return ""


def _prompt_password(label: str) -> str:
    import getpass
    try:
        return getpass.getpass(f"{label}: ")
    except EOFError:
        print(
            f"\nError: cannot prompt for '{label}' — stdin is not a TTY.\n"
            "Run this command directly in a terminal, or pass --password as a flag."
        )
        raise SystemExit(1)


def _api_post_public(url: str, path: str, body: dict) -> tuple[int, dict]:
    import httpx
    r = httpx.post(f"{url}{path}", json=body, timeout=15)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"error": r.text}


def cmd_signup(args: argparse.Namespace) -> int:
    """Create a new CodeBrain account from the CLI."""
    from .config import load as _load_cfg, save as _save_cfg
    import httpx

    url = (getattr(args, "url", None) or "").rstrip("/")
    if not url:
        cfg = _load_cfg()
        url = cfg.get("url", "").rstrip("/")
    if not url:
        url = DEFAULT_URL

    # Health check
    try:
        r = httpx.get(f"{url}/api/v1/health", timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Cannot reach {url}: {e}")
        return 1

    print(f"Connected to {url}")
    username = (getattr(args, "username", None) or "").strip()
    if not username:
        username = _prompt("Choose a username (3–30 chars, letters/digits/_/-)").strip()
    if not username:
        print("Username is required.")
        return 1

    password = getattr(args, "password", None) or ""
    if password:
        if len(password) < 6:
            print("Password must be at least 6 characters.")
            return 1
    else:
        while True:
            password = _prompt_password("Choose a password (6+ chars)")
            if len(password) < 6:
                print("Password must be at least 6 characters.")
                continue
            confirm = _prompt_password("Confirm password")
            if password != confirm:
                print("Passwords do not match, try again.")
                continue
            break

    email = (getattr(args, "email", None) or "").strip()
    if not email:
        email = _prompt_optional("Email (optional, press Enter to skip)")

    status, data = _api_post_public(url, "/api/v1/auth/register", {
        "username": username,
        "password": password,
        "email": email,
    })
    if status == 409:
        print(f"Username '{username}' is already taken. Try a different one or run 'codebrain login'.")
        return 1
    if status != 201:
        print(f"Registration failed: {data.get('error', data)}")
        return 1

    api_key = data["api_key"]
    cfg = _load_cfg()
    cfg.update({"url": url, "api_key": api_key})
    # Save to home directory so credentials are available from any directory
    _save_cfg(cfg, root=Path.home())
    _write_global_claude_md()

    print(f"\nAccount created! Logged in as '{username}'.")
    print(f"Connected to {url}")
    print("Your API key is saved to ~/.codebrain.")
    print("\nNext: run  codebrain new  to set up your first project.")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    """Log in to an existing CodeBrain account and save credentials."""
    from .config import load as _load_cfg, save as _save_cfg
    import httpx

    url = (getattr(args, "url", None) or "").rstrip("/")
    if not url:
        cfg = _load_cfg()
        url = cfg.get("url", "").rstrip("/")
    if not url:
        url = DEFAULT_URL

    try:
        r = httpx.get(f"{url}/api/v1/health", timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Cannot reach {url}: {e}")
        return 1

    username = (getattr(args, "username", None) or "").strip() or _prompt("Username")
    password = getattr(args, "password", None) or _prompt_password("Password")

    status, data = _api_post_public(url, "/api/v1/auth/login", {
        "username": username,
        "password": password,
    })
    if status == 401:
        print("Invalid username or password.")
        return 1
    if status != 200:
        print(f"Login failed: {data.get('error', data)}")
        return 1

    api_key = data["api_key"]
    cfg = _load_cfg()
    cfg.update({"url": url, "api_key": api_key})
    # Save to home directory so credentials are available from any directory
    _save_cfg(cfg, root=Path.home())
    _write_global_claude_md()

    print(f"\nLogged in as '{username}'. Credentials saved to ~/.codebrain.")
    print("Run  codebrain new  to set up a project, or  codebrain up  to verify your connection.")
    return 0


def _select(prompt: str, options: list[str]) -> int:
    """Show a numbered menu, return 0-based index of chosen option."""
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        try:
            raw = input(f"Choice [1–{len(options)}]: ").strip()
        except EOFError:
            print(
                "\nError: cannot prompt for a choice — stdin is not a TTY.\n"
                "Run this command in a terminal, or pass --type local|clone|url to skip this prompt."
            )
            raise SystemExit(1)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"Please enter a number between 1 and {len(options)}.")


def cmd_new(args: argparse.Namespace) -> int:
    """Interactive wizard: create a new project and set up local config files."""
    from .config import load as _load_cfg, save as _save_cfg
    import httpx, subprocess

    cfg = _load_cfg()
    url = (cfg.get("url") or "").rstrip("/")
    api_key = cfg.get("api_key") or ""

    if not url or not api_key:
        print("No credentials found. Run 'codebrain signup' or 'codebrain login' first.")
        return 1

    # Verify the key still works
    try:
        r = httpx.get(f"{url}/api/v1/me", headers={"X-API-Key": api_key}, timeout=10)
        if r.status_code == 401:
            print("Stored API key is invalid. Run 'codebrain login' to refresh it.")
            return 1
        me = r.json()
    except Exception as e:
        print(f"Cannot reach {url}: {e}")
        return 1

    print(f"Logged in as '{me.get('username', '?')}' on {url}\n")

    name = (getattr(args, "name", None) or "").strip() or _prompt("Project name").strip()
    if not name:
        print("Project name is required.")
        return 1

    _TYPE_MAP = {"local": 0, "clone": 1, "url": 2}
    type_flag = (getattr(args, "type", None) or "").strip().lower()
    if type_flag in _TYPE_MAP:
        choice = _TYPE_MAP[type_flag]
        labels = [
            "Scan local directory",
            "Clone from GitHub",
            "Register URL only",
        ]
        print(f"Project type: {labels[choice]}")
    else:
        choice = _select(
            "How do you want to set up this project?",
            [
                "Scan local directory — point to existing code on this machine",
                "Clone from GitHub — enter a repo URL and CodeBrain will clone it",
                "Register URL only — just store the GitHub URL (no local scanning yet)",
            ],
        )

    source_url = ""
    scan_path = None

    if choice == 0:  # local scan
        path_flag = (getattr(args, "path", None) or "").strip()
        scan_path = path_flag or _prompt("Path to source directory", default=".") or "."
        scan_path = str(Path(scan_path).resolve())

    elif choice == 1:  # clone from GitHub
        github_url = (getattr(args, "github_url", None) or "").strip() or \
            _prompt("GitHub repo URL (e.g. https://github.com/you/repo)")
        if not github_url:
            print("GitHub URL is required.")
            return 1
        default_dir = github_url.rstrip("/").split("/")[-1].removesuffix(".git")
        clone_dir = (getattr(args, "clone_dir", None) or "").strip() or \
            _prompt("Local directory to clone into", default=default_dir) or default_dir
        print(f"\nCloning {github_url} into {clone_dir} ...")
        result = subprocess.run(["git", "clone", github_url, clone_dir])
        if result.returncode != 0:
            print("git clone failed. Check the URL and your git credentials.")
            return 1
        scan_path = str(Path(clone_dir).resolve())
        source_url = github_url
        print(f"Cloned to {scan_path}")

    else:  # register URL only
        source_url = (getattr(args, "github_url", None) or "").strip() or \
            _prompt_optional("GitHub repo URL (optional, press Enter to skip)")

    # Create codebase on server
    try:
        rc = httpx.post(
            f"{url}/api/v1/codebases",
            json={"name": name, "source_url": source_url},
            headers={"X-API-Key": api_key},
            timeout=15,
        )
        if rc.status_code in (200, 201):
            codebase_id = rc.json()["id"]
            existed = rc.json().get("existed", False)
            verb = "Using existing" if existed else "Created"
            print(f"\n{verb} codebase '{name}' (id={codebase_id})")
        else:
            import hashlib
            codebase_id = hashlib.sha256(name.encode()).hexdigest()[:8]
            print(f"Warning: could not create codebase via API ({rc.status_code}) — using id={codebase_id}")
    except Exception as e:
        import hashlib
        codebase_id = hashlib.sha256(name.encode()).hexdigest()[:8]
        print(f"Warning: {e} — using id={codebase_id}")

    project_root = Path(scan_path) if scan_path else Path(".")
    force = getattr(args, "force", False)

    # Write .codebrain
    cfg.update({"url": url, "api_key": api_key, "codebase_id": codebase_id, "name": name, "path": str(project_root)})
    _save_cfg(cfg, root=project_root)
    _ensure_gitignore_in(project_root, ".codebrain")
    print("  Wrote .codebrain (gitignored — contains your API key)")

    # Write .mcp.json
    mcp_path = project_root / ".mcp.json"
    if not mcp_path.exists() or force:
        mcp_path.write_text(json.dumps(_make_mcp_json(url, api_key), indent=2), encoding="utf-8")
        print("  Wrote .mcp.json")
    _ensure_gitignore_in(project_root, ".mcp.json")

    # Write .mcp.json.template
    template_path = project_root / ".mcp.json.template"
    if not template_path.exists() or force:
        template_path.write_text(_make_mcp_json_template(url), encoding="utf-8")
        print("  Wrote .mcp.json.template  (commit this — teammates fill in their own credentials)")

    # Write CLAUDE.md
    claude_path = project_root / "CLAUDE.md"
    if not claude_path.exists() or force:
        claude_path.write_text(_make_claude_md(name, codebase_id), encoding="utf-8")
        print("  Wrote CLAUDE.md")

    # Write slash commands
    commands_dir = project_root / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    for fname, make_fn in [
        ("session-start.md", _make_session_start_md),
        ("session-end.md", _make_session_end_md),
        ("explore.md", _make_explore_md),
        ("annotate.md", _make_annotate_md),
        ("investigate.md", _make_investigate_md),
        ("commands.md", _make_commands_md),
    ]:
        p = commands_dir / fname
        if not p.exists() or force:
            p.write_text(make_fn(codebase_id), encoding="utf-8")
            print(f"  Wrote {p.relative_to(project_root)}")

    # Install git hook
    _install_git_hook_in(project_root)

    # Scan if we have a local path
    if scan_path and choice in (0, 1):
        print(f"\nScanning {scan_path} and pushing to CodeBrain ...")
        _run_scan_and_push(scan_path, url, api_key, codebase_id)

    print(f"\nDone! codebase_id={codebase_id}")
    print("\nNext steps:")
    print(f"  1. Open {project_root} in Claude Code")
    if scan_path:
        print("  2. Restart Claude Code to pick up .mcp.json")
        print("  3. Type /project:session-start to begin")
    else:
        print("  2. Run 'codebrain rescan --path .' once you have local code")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from .config import save as _save_cfg
    import httpx

    url = args.url.rstrip("/")
    api_key = args.api_key
    codebase_name = args.name or Path.cwd().name

    print(f"Connecting to {url} ...", flush=True)
    try:
        r = httpx.get(f"{url}/api/v1/health", timeout=10)
        r.raise_for_status()
        print("  API healthy")
    except Exception as e:
        print(f"  Cannot reach {url}: {e}")
        return 1

    try:
        r = httpx.get(f"{url}/api/v1/codebases", headers={"X-API-Key": api_key}, timeout=10)
        if r.status_code == 401:
            print("  Invalid API key.")
            return 1
    except Exception as e:
        print(f"  API key check failed: {e}")
        return 1

    # Get or create codebase
    try:
        existing = r.json()
        cb = next((c for c in existing if c["name"] == codebase_name), None)
        if cb:
            codebase_id = cb["id"]
            print(f"  Using existing codebase '{codebase_name}' (id={codebase_id})")
        else:
            rc = httpx.post(
                f"{url}/api/v1/codebases",
                json={"name": codebase_name, "source_url": args.path or ""},
                headers={"X-API-Key": api_key},
                timeout=10,
            )
            if rc.status_code in (200, 201):
                codebase_id = rc.json().get("id", "")
                print(f"  Created codebase '{codebase_name}' (id={codebase_id})")
            else:
                import hashlib
                codebase_id = hashlib.sha256(codebase_name.encode()).hexdigest()[:8]
                print(f"  Could not create codebase via API — using id={codebase_id}")
    except Exception as e:
        import hashlib
        codebase_id = hashlib.sha256(codebase_name.encode()).hexdigest()[:8]
        print(f"  Warning: {e} — using id={codebase_id}")

    # Write .codebrain config (gitignored — has credentials)
    cfg = {"url": url, "api_key": api_key, "codebase_id": codebase_id, "name": codebase_name, "path": args.path or "."}
    _save_cfg(cfg)
    _ensure_gitignore(".codebrain")
    print("  Wrote .codebrain (gitignored — contains your API key)")

    # Write .mcp.json (gitignored — has credentials + abs paths)
    mcp_path = Path(".mcp.json")
    if not mcp_path.exists() or args.force:
        mcp_path.write_text(json.dumps(_make_mcp_json(url, api_key), indent=2), encoding="utf-8")
        print("  Wrote .mcp.json")
    _ensure_gitignore(".mcp.json")

    # Write .mcp.json.template (safe to commit — placeholder API key)
    template_path = Path(".mcp.json.template")
    if not template_path.exists() or args.force:
        template_path.write_text(_make_mcp_json_template(url), encoding="utf-8")
        print("  Wrote .mcp.json.template  (commit this — teammates fill in Python path + API key)")

    # Write CLAUDE.md
    claude_path = Path("CLAUDE.md")
    if not claude_path.exists() or args.force:
        claude_path.write_text(_make_claude_md(codebase_name, codebase_id), encoding="utf-8")
        print("  Wrote CLAUDE.md")

    # Write slash commands
    commands_dir = Path(".claude") / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    for fname, make_fn in [
        ("session-start.md", _make_session_start_md),
        ("session-end.md", _make_session_end_md),
        ("explore.md", _make_explore_md),
        ("annotate.md", _make_annotate_md),
        ("investigate.md", _make_investigate_md),
        ("commands.md", _make_commands_md),
    ]:
        p = commands_dir / fname
        if not p.exists() or args.force:
            p.write_text(make_fn(codebase_id), encoding="utf-8")
            print(f"  Wrote {p}")

    _install_git_hook()

    if args.scan and args.path:
        print(f"\nScanning {args.path} and pushing to API...", flush=True)
        _run_scan_and_push(args.path, url, api_key, codebase_id)

    print(f"\nDone. codebase_id={codebase_id}")
    print("\nNext steps:")
    print("  1. git add CLAUDE.md .mcp.json.template .claude/ .git-hooks/  &&  git commit")
    print("  2. Restart Claude Code to pick up .mcp.json")
    print("  3. Teammates: pull, copy .mcp.json.template -> .mcp.json, fill in Python path + API key")
    print("  4. Teammates run: codebrain up  (installs the git hook on their machine too)")
    print("  5. Everyone signs up at the webapp with their own username")
    print("  6. Type /project:session-start to begin a session")
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    from .config import load as _load_cfg, migrate as _migrate_cfg

    if _migrate_cfg():
        print("  Migrated .codebrain file → .codebrain/ directory (session.md can now be written)")

    cfg = _load_cfg()
    url = cfg.get("url") or ""
    api_key = cfg.get("api_key") or ""
    codebase_id = cfg.get("codebase_id") or ""

    if not url or not api_key:
        print("No .codebrain config found. Run 'codebrain init --url <url> --api-key <key> --name <name>' first.")
        return 1

    # Detect broken .mcp.json path (e.g. venv was moved/recreated)
    mcp_path = Path(".mcp.json")
    if mcp_path.exists():
        try:
            mcp_cfg = json.loads(mcp_path.read_text(encoding="utf-8"))
            mcp_cmd = mcp_cfg.get("mcpServers", {}).get("codebrain", {}).get("command", "")
            if mcp_cmd and mcp_cmd != "codebrain" and not Path(mcp_cmd).exists():
                print(f"  WARNING: .mcp.json points to a Python path that no longer exists:")
                print(f"    {mcp_cmd}")
                print("  Run: codebrain upgrade  to update it to your current Python path.")
        except Exception:
            pass

    print(f"Connecting to CodeBrain at {url} ...", flush=True)
    try:
        import httpx
        r = httpx.get(f"{url}/api/v1/health", timeout=10)
        r.raise_for_status()
        health = r.json()
        server_version = str(health.get("version", "1"))
        try:
            from .mcp_server_http import CLIENT_VERSION
        except ImportError:
            CLIENT_VERSION = "1"
            print("  WARNING: Wrong package installed — 'codebrain' on PyPI is a different tool.")
            print("  Run: pip uninstall codebrain && pip install git+https://github.com/DawerJ/CodeBrain-CLI.git")
        if server_version != CLIENT_VERSION:
            print(f"  Version mismatch: local package is v{CLIENT_VERSION}, server expects v{server_version}")
            print(f"     Run: pip install --upgrade git+https://github.com/DawerJ/CodeBrain-CLI.git  then restart Claude Code")
        else:
            print(f"  Connected — API healthy (v{server_version})")
    except Exception as e:
        print(f"  Cannot reach {url}: {e}")
        return 1

    try:
        import httpx
        r = httpx.get(f"{url}/api/v1/codebases", headers={"X-API-Key": api_key}, timeout=10)
        if r.status_code == 401:
            print("  Invalid API key — visit the webapp to rotate your key.")
            return 1
        codebases = r.json()
        print(f"  API key valid — {len(codebases)} codebase(s) accessible")
    except Exception as e:
        print(f"  API key check failed: {e}")
        return 1

    if codebase_id:
        print(f"  Codebase: {codebase_id}")

    _install_git_hook()
    if _write_global_claude_md():
        print("  Global ~/.claude/CLAUDE.md updated.")
    print(f"\nWebapp: {url}")
    print("MCP server: configured in .mcp.json (Claude Code loads it automatically)")

    _check_client_files_up_to_date(
        codebase_id,
        codebase_name=cfg.get("name") or Path.cwd().name,
        url=url,
        api_key=api_key,
    )

    print("\nYou're ready. Open Claude Code and run /project:session-start")

    if getattr(args, "watch", False):
        src_path = cfg.get("path") or "."
        _start_watcher(src_path, url, api_key, codebase_id)

    return 0


def cmd_upgrade() -> int:
    from .config import load as _load_cfg

    cfg = _load_cfg()
    codebase_id = cfg.get("codebase_id") or ""
    codebase_name = cfg.get("name") or Path.cwd().name
    url = cfg.get("url") or ""
    api_key = cfg.get("api_key") or ""

    if not codebase_id:
        print("No .codebrain config found. Run 'codebrain init' first.")
        return 1

    updated: list[str] = []
    skipped: list[str] = []

    def _write_if_changed(path: Path, new_content: str) -> None:
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing == new_content:
            skipped.append(str(path))
        else:
            path.write_text(new_content, encoding="utf-8")
            updated.append(str(path))

    _write_if_changed(Path("CLAUDE.md"), _fetch_template(url, api_key, "CLAUDE.md", codebase_id, codebase_name))

    commands_dir = Path(".claude") / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    for fname in ["session-start.md", "session-end.md", "explore.md", "annotate.md", "investigate.md", "commands.md"]:
        _write_if_changed(commands_dir / fname, _fetch_template(url, api_key, fname, codebase_id, codebase_name))

    _install_git_hook()
    if _write_global_claude_md():
        updated.append(str(Path.home() / ".claude" / "CLAUDE.md"))

    # Patch .mcp.json if it exists and has an outdated codebrain server entry.
    mcp_path = Path(".mcp.json")
    if mcp_path.exists():
        try:
            mcp_cfg = json.loads(mcp_path.read_text(encoding="utf-8"))
            cb = mcp_cfg.get("mcpServers", {}).get("codebrain", {})
            # Migrate: old HTTP/SSE transport OR generic "codebrain" command (no explicit path).
            # A custom absolute path (e.g. /path/to/python.exe) survives unchanged.
            needs_patch = (
                "url" in cb
                or cb.get("type") == "sse"
                or cb.get("command") == "codebrain"
            )
            if needs_patch and ("CODEBRAIN_URL" in cb.get("env", {}) or url):
                cb_env = cb.get("env", {})
                mcp_cfg.setdefault("mcpServers", {})["codebrain"] = {
                    "command": sys.executable,
                    "args": ["-m", "codebrain", "mcp"],
                    "env": {
                        "CODEBRAIN_URL": cb_env.get("CODEBRAIN_URL", url),
                        "CODEBRAIN_API_KEY": cb_env.get("CODEBRAIN_API_KEY", api_key),
                    },
                }
                mcp_path.write_text(
                    json.dumps(mcp_cfg, indent=2) + "\n", encoding="utf-8"
                )
                updated.append(str(mcp_path))
        except Exception:
            pass  # malformed .mcp.json — leave it alone

    if updated:
        print("Updated:")
        for f in updated:
            print(f"  {f}")
    if skipped:
        print("Already up to date:")
        for f in skipped:
            print(f"  {f}")

    if updated:
        _show_changelog(url)
        print("Restart Claude Code to pick up any changes to slash commands.")
        print("Commit the updated files: git add CLAUDE.md .mcp.json .claude/ && git commit -m 'chore: upgrade codebrain client files'")
    else:
        print("\nEverything is already up to date.")

    return 0


def cmd_ci(force: bool = False) -> int:
    from .config import load as _load_cfg

    cfg = _load_cfg()
    codebase_id = cfg.get("codebase_id") or ""
    if not codebase_id:
        print("No .codebrain config found. Run 'codebrain init' first.")
        return 1

    workflow_dir = Path(".github") / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / "codebrain.yml"

    if workflow_path.exists() and not force:
        print(f"{workflow_path} already exists. Use --force to overwrite.")
        return 0

    workflow_path.write_text(_make_ci_workflow(codebase_id), encoding="utf-8")
    print(f"Wrote {workflow_path}")
    print("\nNext steps:")
    print("  1. Add these secrets to your GitHub repo (Settings -> Secrets -> Actions):")
    print(f"       CODEBRAIN_URL        — your CodeBrain server URL")
    print(f"       CODEBRAIN_API_KEY    — your CI API key (get from webapp Settings)")
    print(f"  2. git add .github/ && git commit -m 'chore: add codebrain CI workflow'")
    print(f"  3. Push — the workflow runs automatically on every Python file change")
    return 0


def cmd_rescan(args: argparse.Namespace) -> int:
    from .config import load as _load_cfg

    cfg = _load_cfg() or {}
    url = (getattr(args, "url", None) or os.environ.get("CODEBRAIN_URL") or cfg.get("url", "")).rstrip("/")
    api_key = getattr(args, "api_key", None) or os.environ.get("CODEBRAIN_API_KEY") or cfg.get("api_key", "")
    codebase_id = (
        getattr(args, "codebase_id", None)
        or os.environ.get("CODEBRAIN_CODEBASE_ID")
        or cfg.get("codebase_id", "")
    )
    path = getattr(args, "path", ".") or "."

    if not url or not api_key:
        print("Error: need --url and --api-key (or CODEBRAIN_URL / CODEBRAIN_API_KEY env vars)")
        return 1

    print(f"Scanning {path} ...", flush=True)
    try:
        _run_scan_and_push(path, url, api_key, codebase_id)
    except Exception as e:
        print(f"Rescan failed: {e}")
        return 1
    print("Rescan complete.")
    return 0


def _start_watcher(src_path: str, url: str, api_key: str, codebase_id: str) -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        import httpx, time

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory or not event.src_path.endswith(".py"):
                    return
                print(f"  [watcher] {event.src_path} changed — pushing rescan", flush=True)
                try:
                    httpx.post(
                        f"{url}/api/v1/report-change",
                        json={"codebase_id": codebase_id, "new_file_paths": [event.src_path]},
                        headers={"X-API-Key": api_key},
                        timeout=10,
                    )
                except Exception as e:
                    print(f"  [watcher] error: {e}", flush=True)

        observer = Observer()
        observer.schedule(_Handler(), src_path, recursive=True)
        observer.start()
        print(f"\nWatcher started on {src_path} — Ctrl+C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
    except ImportError:
        print("  Install watchdog to enable file watching: pip install watchdog")


# ── Demo command ─────────────────────────────────────────────────────────────

def cmd_demo(args: argparse.Namespace) -> int:
    """Build a real, indexed codebase from scratch and feel what CodeBrain gives you."""
    import time
    import httpx
    from .config import load as _load_cfg, save as _save_cfg

    cfg = _load_cfg()
    url = (getattr(args, "url", None) or cfg.get("url") or DEFAULT_URL).rstrip("/")
    api_key = cfg.get("api_key") or ""

    if not api_key:
        print("No account found. Run 'codebrain signup' first.")
        return 1

    # ── Intro ──────────────────────────────────────────────────────────────────
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║              CodeBrain — build something real                ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print("  In the next few minutes you will build a production-ready")
    print("  codebase from scratch. CodeBrain will index every function,")
    print("  map the architecture, and be ready to teach you the moment")
    print("  Claude Code opens.")
    print()
    print("  This is how AI coding was meant to work.")
    print()

    # ── Project type selection ─────────────────────────────────────────────────
    options = [
        ("task_manager",     "Task Management Platform",    "projects, tasks, teams, deadlines"),
        ("notes_app",        "AI-Powered Notes App",        "capture, search, AI summarization"),
        ("api_service",      "Developer API Service",       "auth, rate limiting, API versioning"),
        ("content_platform", "Content Publishing Platform", "posts, users, social feeds"),
    ]

    print("  What kind of company are you starting?\n")
    for i, (_, name, desc) in enumerate(options, 1):
        print(f"    {i}. {name}")
        print(f"       {desc}")
        print()

    while True:
        try:
            raw = input("  Choose (1–4): ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                break
            print("  Enter a number between 1 and 4.")
        except (ValueError, EOFError):
            print("  Enter a number between 1 and 4.")

    project_type, project_name, project_desc = options[idx]
    print()
    print(f"  Building your {project_name}...")
    print()

    # ── Call server ────────────────────────────────────────────────────────────
    try:
        r = httpx.post(
            f"{url}/api/v1/demo/generate",
            json={"project_type": project_type},
            headers={"X-API-Key": api_key},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  Server error {r.status_code}: {r.text[:200]}")
            return 1
        data = r.json()
    except Exception as e:
        print(f"  Could not reach CodeBrain server: {e}")
        return 1

    codebase_id = data["codebase_id"]
    slug = data["slug"]
    tagline = data.get("tagline", "")
    files = data["files"]

    # ── Create project directory ───────────────────────────────────────────────
    project_dir = Path.cwd() / slug
    project_dir.mkdir(exist_ok=True)

    # ── Write files with narration ─────────────────────────────────────────────
    print(f"  ┌─ {project_name}")
    print(f"  │  {tagline}")
    print(f"  │")
    total_functions = 0
    for file_info in files:
        file_path = project_dir / file_info["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"  │  Writing {file_info['path']}...", end="", flush=True)
        time.sleep(0.35)
        file_path.write_text(file_info["content"], encoding="utf-8")
        print(" ✓")

        insight = file_info.get("insight", "")
        if insight:
            # Word-wrap insight to 56 chars
            words = insight.split()
            lines, line = [], []
            for w in words:
                if sum(len(x) + 1 for x in line) + len(w) > 56:
                    lines.append(" ".join(line))
                    line = [w]
                else:
                    line.append(w)
            if line:
                lines.append(" ".join(line))
            print(f"  │  [CodeBrain] {lines[0]}")
            for l in lines[1:]:
                print(f"  │             {l}")
        print(f"  │")

    print(f"  └─ Done. {len(files)} files written.")
    print()

    # ── Count functions (scan what was written) ────────────────────────────────
    import ast, hashlib as _hashlib
    units = []
    for py_file in project_dir.rglob("*.py"):
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(py_file))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_src = ast.get_source_segment(src, node) or ""
                units.append({
                    "name": node.name,
                    "file_path": str(py_file),
                    "source": fn_src,
                    "source_hash": _hashlib.sha256(fn_src.encode()).hexdigest()[:16],
                    "cyclomatic_complexity": 1,
                    "criticality_score": 0.5,
                    "profile_name": "STANDARD",
                })
    total_functions = len(units)

    # ── Push to CodeBrain ──────────────────────────────────────────────────────
    print(f"  Indexing {total_functions} functions into CodeBrain...", end="", flush=True)
    try:
        for i in range(0, len(units), 50):
            batch = units[i:i + 50]
            r2 = httpx.post(
                f"{url}/api/v1/code-units",
                json={"codebase_id": codebase_id, "units": batch},
                headers={"X-API-Key": api_key},
                timeout=60,
            )
            r2.raise_for_status()
        print(" ✓")
    except Exception as e:
        print(f"\n  Warning: indexing failed ({e}). You can run 'codebrain rescan' later.")

    # ── Push seed data (architecture, feature mappings, learn content) ─────────
    seed = data.get("seed_data", {})
    if seed:
        _hdrs = {"X-API-Key": api_key}
        _base = {"codebase_id": codebase_id}

        if seed.get("architecture"):
            try:
                httpx.put(f"{url}/api/v1/architecture",
                          json={**_base, "content": seed["architecture"]},
                          headers=_hdrs, timeout=15)
            except Exception:
                pass

        if seed.get("feature_mappings"):
            try:
                httpx.post(f"{url}/api/v1/feature-mapping",
                           json={**_base, "mappings": seed["feature_mappings"]},
                           headers=_hdrs, timeout=30)
            except Exception:
                pass

        for lc in seed.get("learn_content", []):
            try:
                httpx.post(f"{url}/api/v1/learn-content",
                           json={**_base, **lc},
                           headers=_hdrs, timeout=15)
            except Exception:
                pass

    # ── Save local config ──────────────────────────────────────────────────────
    _save_cfg(
        {"url": url, "api_key": api_key, "codebase_id": codebase_id,
         "name": project_name, "path": str(project_dir)},
        root=project_dir,
    )
    _ensure_gitignore_in(project_dir, ".codebrain")
    _ensure_gitignore_in(project_dir, ".mcp.json")
    _ensure_gitignore_in(project_dir, "__pycache__/")
    _ensure_gitignore_in(project_dir, "*.pyc")

    # ── Initialize git repo ────────────────────────────────────────────────────
    import subprocess as _sp
    try:
        _sp.run(["git", "init"], cwd=str(project_dir), check=True,
                capture_output=True, text=True)
    except Exception:
        pass  # git not installed or already a repo — non-fatal

    # ── Write CodeBrain project files ──────────────────────────────────────────
    _write_mcp_json_in(project_dir, url, api_key, codebase_id)
    (project_dir / "CLAUDE.md").write_text(
        _make_claude_md(project_name, codebase_id), encoding="utf-8"
    )
    commands_dir = project_dir / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    (commands_dir / "session-start.md").write_text(
        _make_session_start_md(codebase_id), encoding="utf-8"
    )
    (commands_dir / "session-end.md").write_text(
        _make_session_end_md(codebase_id), encoding="utf-8"
    )
    demo_script = data.get("demo_script", "")
    if demo_script:
        (commands_dir / "demo.md").write_text(demo_script, encoding="utf-8")

    # ── North star moment ──────────────────────────────────────────────────────
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                                                              ║")
    print(f"║  Your {project_name:<53}║")
    print("║  is ready.                                                   ║")
    print("║                                                              ║")
    print(f"║  {total_functions} functions indexed. CodeBrain knows how they connect,  ║")
    print("║  what they depend on, and what could break.                  ║")
    print("║                                                              ║")
    print("║  From nothing to full codebase ownership in minutes.         ║")
    print("║  One person. No ceiling.                                     ║")
    print("║                                                              ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print("  Next steps:")
    print(f"    cd {slug}")
    print(f"    code .")
    print()
    print("  When VS Code opens, reload once so Claude picks up the MCP config:")
    print("    Ctrl+Shift+P  →  Developer: Reload Window")
    print()
    print("  Then start the experience:")
    print(f"    /project:demo")
    print()
    print("  CodeBrain will walk you through your codebase — and throw")
    print("  a real production crisis at you when you're ready.")
    print()
    return 0


def _ensure_gitignore_in(project_dir: Path, entry: str) -> None:
    gi = project_dir / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if entry not in existing.splitlines():
        with gi.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"{entry}\n")


def _write_mcp_json_in(project_dir: Path, url: str, api_key: str, codebase_id: str) -> None:
    """Write .mcp.json for the demo project using stdio transport."""
    import json as _json
    # Use stdio transport (runs local mcp_server_http module via python -m) —
    # the HTTP URL transport requires a /mcp SSE endpoint on the server which isn't exposed.
    mcp = _make_mcp_json(url, api_key)
    (project_dir / ".mcp.json").write_text(_json.dumps(mcp, indent=2), encoding="utf-8")


def cmd_delete_demo(args: argparse.Namespace) -> int:
    """Delete one or all demo codebases from the server."""
    import httpx
    import logging as _logging
    _logging.getLogger("httpx").setLevel(_logging.WARNING)
    _logging.getLogger("httpcore").setLevel(_logging.WARNING)
    from .config import load as _load_cfg

    cfg = _load_cfg()
    url = (getattr(args, "url", None) or cfg.get("url") or DEFAULT_URL).rstrip("/")
    api_key = cfg.get("api_key") or ""

    if not api_key:
        print("No account found. Run 'codebrain signup' first.")
        return 1

    hdrs = {"X-API-Key": api_key}

    try:
        r = httpx.get(f"{url}/api/v1/demo/list", headers=hdrs, timeout=15)
        r.raise_for_status()
        demos = r.json().get("demos", [])
    except Exception as e:
        print(f"  Could not fetch demo list: {e}")
        return 1

    if not demos:
        print("  No demo codebases found.")
        return 0

    codebase_id_flag = getattr(args, "codebase_id", None)
    all_flag = getattr(args, "all", False)

    if codebase_id_flag:
        targets = [d for d in demos if d["id"] == codebase_id_flag]
        if not targets:
            print(f"  Demo codebase '{codebase_id_flag}' not found.")
            return 1
    elif all_flag:
        targets = demos
    else:
        print()
        print("  Demo codebases in your account:\n")
        for i, d in enumerate(demos, 1):
            print(f"    {i}. {d['name']}  (id: {d['id']})  created: {d['created_at'][:10]}")
        print(f"    {len(demos) + 1}. Delete all")
        print()
        while True:
            try:
                raw = input(f"  Delete which? (1-{len(demos) + 1}): ").strip()
                idx = int(raw) - 1
                if idx == len(demos):
                    targets = demos
                    break
                elif 0 <= idx < len(demos):
                    targets = [demos[idx]]
                    break
                else:
                    print(f"  Enter a number between 1 and {len(demos) + 1}.")
            except (ValueError, EOFError):
                print("  Cancelled.")
                return 0

    print()
    for demo in targets:
        cid = demo["id"]
        name = demo["name"]
        print(f"  Deleting {name} ({cid})...", end="", flush=True)
        try:
            r = httpx.delete(f"{url}/api/v1/demo/{cid}", headers=hdrs, timeout=15)
            if r.status_code == 200:
                print(" ok")
            else:
                print(f" failed ({r.status_code}: {r.text[:80]})")
        except Exception as e:
            print(f" error: {e}")

    print()
    print("  Done. To also remove local directories, delete them manually:")
    print("    Remove-Item -Recurse -Force <project-folder>")
    print()
    return 0


# ── Agent test commands ───────────────────────────────────────────────────────

def cmd_test(args: argparse.Namespace) -> int:
    """Run agent integration tests against CodeBrain."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        print("The 'anthropic' package is required for agent tests.")
        print("Run: pip install anthropic")
        return 1

    runner = Path(__file__).parent.parent.parent / "tests" / "agent_test_runner.py"
    if not runner.exists():
        print(f"Test runner not found: {runner}")
        print("Clone the full codebrain repo to use agent tests.")
        return 1

    cmd = [sys.executable, str(runner),
           "--mode", args.mode,
           "--agents", str(args.agents),
           "--model", args.model,
           "--skill", args.skill]
    if args.run_id:
        cmd += ["--run-id", args.run_id]

    import subprocess as _sp
    result = _sp.run(cmd)
    return result.returncode


def cmd_test_results(args: argparse.Namespace) -> int:
    """View agent test reports."""
    from .config import require as _require_cfg
    cfg = _require_cfg()
    url = cfg["url"]
    api_key = cfg["api_key"]

    params: dict = {"limit": args.limit}
    if args.run_id:
        params["run_id"] = args.run_id
    if args.status:
        params["status"] = args.status

    try:
        import httpx as _httpx
        r = _httpx.get(
            f"{url}/api/v1/agent-test-reports",
            params=params,
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"Error fetching reports: {e}")
        return 1

    data = r.json()
    reports = data.get("reports", [])
    if not reports:
        print("No reports found.")
        return 0

    print(f"\nAgent Test Reports ({data.get('total', len(reports))} shown)\n")
    print(f"{'Created':<20} {'Run ID':<14} {'Type':<10} {'Sev':<8} {'Status':<10} Description")
    print("-" * 100)
    for rep in reports:
        created = rep.get("created_at", "")[:16]
        run = rep.get("run_id", "")[:12]
        rtype = rep.get("report_type", "")[:9]
        sev = rep.get("severity", "")[:7]
        status = rep.get("status", "")[:9]
        desc = rep.get("description", "")[:55]
        print(f"{created:<20} {run:<14} {rtype:<10} {sev:<8} {status:<10} {desc}")

    return 0


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def main() -> None:
    import io as _io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="codebrain",
        description="CodeBrain CLI — connect your codebase to the CodeBrain understanding layer",
    )
    sub = parser.add_subparsers(dest="command")

    # signup
    p_signup = sub.add_parser("signup", help="Create a new CodeBrain account")
    p_signup.add_argument("--url", default=None, help="CodeBrain server URL")
    p_signup.add_argument("--username", default=None, help="Username (skips interactive prompt)")
    p_signup.add_argument("--password", default=None, help="Password (skips interactive prompt)")
    p_signup.add_argument("--email", default=None, help="Email address (optional)")

    # login
    p_login = sub.add_parser("login", help="Log in to an existing account and save credentials locally")
    p_login.add_argument("--url", default=None, help="CodeBrain server URL")
    p_login.add_argument("--username", default=None, help="Username (skips interactive prompt)")
    p_login.add_argument("--password", default=None, help="Password (skips interactive prompt)")

    # new
    p_new = sub.add_parser("new", help="Create a new project and set up local config files (interactive)")
    p_new.add_argument("--name", default=None, help="Project name (skips interactive prompt)")
    p_new.add_argument("--type", default=None, choices=["local", "clone", "url"],
                       help="Project type: local (scan directory), clone (git clone), url (register URL only)")
    p_new.add_argument("--path", default=None, help="Source directory to scan (for --type local)")
    p_new.add_argument("--github-url", default=None, dest="github_url",
                       help="GitHub repo URL (for --type clone or url)")
    p_new.add_argument("--clone-dir", default=None, dest="clone_dir",
                       help="Local directory to clone into (for --type clone, default: repo name)")
    p_new.add_argument("--force", action="store_true", help="Overwrite existing config files")

    # init
    p_init = sub.add_parser("init", help="Bootstrap a project — connect to a CodeBrain server (non-interactive)")
    p_init.add_argument("--name", default=None, help="Codebase name (defaults to current directory name)")
    p_init.add_argument("--url", required=True, help="CodeBrain server URL (e.g. https://yourapp.railway.app)")
    p_init.add_argument("--api-key", required=True, dest="api_key",
                        help="Your CodeBrain API key (get from webapp Settings -> API Key)")
    p_init.add_argument("--path", default=None, help="Source directory to scan and push")
    p_init.add_argument("--scan", action="store_true",
                        help="Scan --path and push code units to the server after setup")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing config files")

    # upgrade
    sub.add_parser(
        "upgrade",
        help="Refresh CLAUDE.md, slash commands, and git hook to the latest templates",
    )

    # ci
    p_ci = sub.add_parser(
        "ci",
        help="Scaffold a GitHub Actions workflow that rescans changed Python files on push",
    )
    p_ci.add_argument("--force", action="store_true", help="Overwrite existing workflow file")

    # demo
    p_demo = sub.add_parser(
        "demo",
        help="Build a real, CodeBrain-indexed codebase from scratch — see what's possible",
    )
    p_demo.add_argument("--url", default=None, help="CodeBrain server URL (optional)")

    # delete-demo
    p_del = sub.add_parser(
        "delete-demo",
        help="Delete demo codebase(s) from the server",
    )
    p_del.add_argument("--url", default=None, help="CodeBrain server URL (optional)")
    p_del.add_argument("--codebase-id", default=None, dest="codebase_id",
                       help="Delete a specific demo codebase by ID")
    p_del.add_argument("--all", action="store_true", default=False,
                       help="Delete all demo codebases without prompting")

    # mcp
    sub.add_parser("mcp", help="Start the MCP server (used by Claude Code via .mcp.json)")

    # up
    p_up = sub.add_parser("up", help="Verify connection and optionally start file watcher")
    p_up.add_argument("--watch", action="store_true",
                      help="Start a file watcher that notifies CodeBrain on .py file saves")

    # rescan
    p_rescan = sub.add_parser(
        "rescan",
        help="Scan source files and push changed code units to CodeBrain (used by CI)",
    )
    p_rescan.add_argument("--path", default=".", help="Source directory to scan (default: .)")
    p_rescan.add_argument("--url", default=None, help="CodeBrain server URL")
    p_rescan.add_argument("--api-key", default=None, dest="api_key", help="CodeBrain API key")
    p_rescan.add_argument("--codebase-id", default=None, dest="codebase_id",
                          help="Codebase ID (falls back to .codebrain or CODEBRAIN_CODEBASE_ID env)")

    # test
    p_test = sub.add_parser("test", help="Run agent integration tests against CodeBrain")
    p_test.add_argument("--mode", choices=["sandbox", "prod"], default="sandbox")
    p_test.add_argument("--agents", type=int, choices=[1, 2], default=1)
    p_test.add_argument("--model", choices=["haiku", "sonnet"], default="haiku")
    p_test.add_argument("--skill", choices=["novice", "intermediate", "expert"], default="intermediate")
    p_test.add_argument("--run-id", default=None, dest="run_id")

    # test-results
    p_results = sub.add_parser("test-results", help="View agent integration test reports")
    p_results.add_argument("--run-id", default=None, dest="run_id")
    p_results.add_argument("--status", choices=["open", "reviewed", "resolved"], default="open")
    p_results.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.command == "signup":
        sys.exit(cmd_signup(args))
    elif args.command == "login":
        sys.exit(cmd_login(args))
    elif args.command == "new":
        sys.exit(cmd_new(args))
    elif args.command == "init":
        sys.exit(cmd_init(args))
    elif args.command == "upgrade":
        sys.exit(cmd_upgrade())
    elif args.command == "ci":
        sys.exit(cmd_ci(force=getattr(args, "force", False)))
    elif args.command == "mcp":
        # Windows ProactorEventLoop (default in Python 3.8+) is incompatible with
        # stdio pipes used by Claude Code / Electron. SelectorEventLoop works correctly.
        if sys.platform == "win32":
            import asyncio, io
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            # Electron sets PYTHONUNBUFFERED=1, leaving stdout as raw FileIO.
            # MCP stdio requires line-buffered output — flush after each \n so
            # JSON-RPC responses are sent immediately. Block buffering (BufferedWriter)
            # causes deadlock when used as a subprocess: responses sit in buffer until
            # it fills, never reaching the reader.
            if hasattr(sys.stdout, "buffer"):
                sys.stdout = io.TextIOWrapper(
                    sys.stdout.buffer, encoding="utf-8", line_buffering=True
                )
        from .mcp_server_http import mcp as _mcp
        _mcp.run()
    elif args.command == "up":
        sys.exit(cmd_up(args))
    elif args.command == "rescan":
        sys.exit(cmd_rescan(args))
    elif args.command == "demo":
        sys.exit(cmd_demo(args))
    elif args.command == "delete-demo":
        sys.exit(cmd_delete_demo(args))
    elif args.command == "test":
        sys.exit(cmd_test(args))
    elif args.command == "test-results":
        sys.exit(cmd_test_results(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
