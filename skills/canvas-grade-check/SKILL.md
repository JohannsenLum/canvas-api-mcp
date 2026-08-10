---
name: canvas-grade-check
description: Works out a student's current standing in a Canvas LMS course, computing remaining unearned points from live grades and assignment data. Use when a student asks "what's my grade", "how am I doing in this course", "what do I need to get an A/pass", or wants to know their standing, remaining points, or what score is needed on upcoming work.
---

# Canvas Grade Check

Read-only analysis skill. Never modify, submit, or post anything: only compute from what
the canvas-api-mcp tools return.

## Prerequisites

The `canvas-api-mcp` MCP server must be installed and connected in the current client.
If tool calls to `my_courses`, `my_grades`, or `list_assignments` are not available, tell
the user to install it first: https://mcp.johannsenlum.com/canvas-lms/install

## Procedure

1. **Identify the course.** Call `my_courses` to find the course in question. If the
   student named it, match it; if ambiguous, ask or list candidates rather than guessing.

2. **Get current grades.** Call `my_grades` for the identified course to get the current
   score/grade as Canvas reports it.

3. **Get assignment detail.** Call `list_assignments` for the course to get, for every
   assignment: points_possible and submission/grading state (graded, submitted-ungraded,
   not submitted, not yet due).

4. **Compute remaining unearned points.**
   - Sum `points_possible` for assignments that are not yet graded (ungraded-submitted,
     not-yet-due, not submitted): this is the pool of points still in play.
   - Sum points already earned from graded work (as reported by the tools).
   - Do not estimate a score for anything not yet graded: treat it as unresolved
     potential, not a guessed number.

5. **State current standing and what's needed:**
   - Report the current grade/score exactly as `my_grades` reports it.
   - Report total possible points, points earned so far, and points remaining
     (ungraded/outstanding), from step 4.
   - If asked "what do I need to get X", compute the math to that answer ONLY if
     points_possible for all remaining work is known and the weighting scheme is either
     visible via the API or the student's assumption is used explicitly (see below),
     otherwise present the arithmetic range that is knowable and stop there.

6. **State weighting assumptions explicitly.** Canvas courses may use weighted
   assignment groups instead of raw points. If the tools do not expose group weights:
   - Say plainly that the grading/weighting scheme is not visible via the API.
   - Do not invent or assume a weighting scheme (e.g. do not assume "everything is
     equally weighted" silently). If a raw-points calculation is shown anyway as a
     rough approximation, label it clearly as "unweighted approximation, may not match
     the instructor's actual weighting". Never present it as the real grade.

## Rules

- Every number in the output (score, points possible, points earned, points remaining)
  must come from a tool call in this session. Never estimate or guess a grade.
- Never guess deadlines or invent submission states: read them from `list_assignments`.
- If weighting is unknown, say so explicitly rather than assuming equal weighting.
- Do not call any write tool. This skill is strictly read-only.

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `my_courses` | Identify/confirm the target course |
| `my_grades` | Get current grade/score for the course |
| `list_assignments` | Get points_possible and submission/grading state per assignment |
