---
name: canvas-week-plan
description: Plans the coming days of Canvas LMS coursework by pulling upcoming due dates, resolving course names, checking submission status, and building a due-date-ordered table with urgency flags. Use when a student asks "what's due", "what do I have coming up", "plan my week/days", wants a schedule of upcoming assignments, or asks whether anything is due soon or overdue.
---

# Canvas Week Plan

Read-only planning skill. Never modify, submit, or post anything — only report what the
canvas-api-mcp tools return.

## Prerequisites

The `canvas-api-mcp` MCP server must be installed and connected in the current client.
If tool calls to `whats_due`, `my_courses`, or `my_submission` are not available, tell
the user to install it first: https://mcp.johannsenlum.com/canvas-lms/install

## Procedure

1. **Get upcoming work.** Call the MCP tool `whats_due` to retrieve assignments/items due
   in the near term. Do not guess or estimate due dates — use only what the tool returns.

2. **Resolve course names.** Call `my_courses` and join each item from step 1 to its
   course name/code using the course id. Do not invent a course name if it can't be
   matched — show the raw course id instead and note it's unresolved.

3. **Disambiguate anything unclear.** For any item where submission/completion state is
   ambiguous or missing from step 1's output, call `my_submission` for that specific
   assignment to get its authoritative submitted/graded state. Do not assume "not shown"
   means "not submitted" — check before reporting.

4. **Build the table.** Present the results as a single table ordered by due date
   (soonest first), with these columns:
   - Course (resolved name, or course id + "(unresolved)")
   - Assignment
   - Due date/time
   - Days remaining (compute from the due date and current time only — do not invent a
     "today" if it isn't available from context)
   - Submitted state (Submitted / Not submitted / Graded / Unknown — from tool output only)

5. **Flag risk items**, called out clearly below the table (not buried in it):
   - Anything due within 48 hours that is NOT submitted — flag explicitly, e.g.
     "DUE SOON, UNSUBMITTED".
   - Any two or more items that share the same due date/day ("same-day collision") —
     list them together so the student sees the pile-up.

6. Check whether `whats_due` actually answered. If it returns `{"error": true, ...}` with
   no `items` key, every source failed to load — that is **not** an empty schedule. Say
   Canvas could not be reached and quote the `warnings`; never turn a failed read into
   "nothing is due".

   If it returns `items: []`, that is a real answer: say plainly that nothing is due in the
   window covered by the tool — do not fabricate a "nothing due" conclusion beyond what the
   tool covers, and mention the tool's window/limits if known.

## Rules

- Every fact in the output (due date, course, submission state) must trace back to a tool
  call in this session. Never estimate, round, or "fill in" a due date or status.
- If a tool call fails or returns partial data, say so in the output rather than silently
  omitting affected items.
- Do not call any write tool. This skill is strictly read-only.

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `whats_due` | Fetch upcoming due items across courses |
| `my_courses` | Resolve course ids to names/codes |
| `my_submission` | Check authoritative submission state for an ambiguous assignment |
