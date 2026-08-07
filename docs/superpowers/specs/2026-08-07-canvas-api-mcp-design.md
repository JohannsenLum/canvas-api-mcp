# canvas-api-mcp — Design

**Date:** 2026-08-07
**Status:** Approved design, pending implementation plan

## Goal

An MCP server that lets any AI agent read and act on a user's Canvas LMS account —
serving students and educators, installable by anyone at any institution.

Primary user is the author (NUS student). Secondary users are peers at NUS and, if it
gains traction, educators and students at other institutions. Open source (MIT), built
to accept forks and pull requests.

## Non-goals

- No hosted/shared deployment. Every user runs their own local process with their own
  token. Hosting would mean custodying other people's Canvas credentials, which carries
  liability and operational burden with no offsetting benefit.
- No institution-specific hardcoding. NUS is the first test instance, not the target.
- Not competing on curated-tool count with existing Canvas MCP servers. The tool surface
  is deliberately small; completeness comes from the gateway layer.

## Background

NUS runs a stock Instructure Canvas instance at `https://canvas.nus.edu.sg`, behind SAML
SSO (`/login/saml/210`). SSO gates *browser* login only; the REST API authenticates
separately via bearer token, so no SAML handling is needed.

The instance serves its own machine-readable spec (Swagger 1.2) at
`/doc/api/api-docs.json`, enumerating 143 resource files. Extracting all of them yields
the authoritative endpoint map for that exact deployment:

| Metric | Count |
|---|---|
| Total endpoints | 1,116 |
| Resource families | 142 |
| GET (read) | 562 |
| POST / PUT / PATCH / DELETE (write) | 554 |
| Account-scoped (admin) | 222 |
| Course-scoped (student or teacher) | 430 |
| `users/self` (student-safe) | 34 |

Two facts drive the architecture:

1. Real usage is extremely concentrated. "What's due this week?" is answered by two
   endpoints (`/users/self/todo`, `/users/self/upcoming_events`) out of 1,116.
2. The long tail is genuinely needed but unpredictable, especially for educators.

Exposing 1,116 endpoints as 1,116 tools is not viable: tool-selection accuracy degrades
as the list grows, and every tool schema costs context on every turn. Exposing only a
curated subset permanently orphans the long tail and requires hand-writing a new tool
each time Instructure ships an endpoint.

## Architecture

Three layers.

**Layer 1 — Curated tools (22).** Named after jobs, not endpoints. Carry real ergonomics:
`whats_due()` fans out to two endpoints and merges results, because that is what the
question means. Covers the high-frequency student and educator workflows.

**Layer 2 — Discovery.** `search_canvas_api(query)` ranks matches over an embedded
catalog of all 1,116 endpoints (method, path, nickname, summary, parameters).

**Layer 3 — Passthrough.** `canvas_request(method, path, params, body, dry_run)` executes
any endpoint the search surfaces.

Result: complete API reach at 24 tool schemas (22 curated + 2 gateway).

```
"what's due this week"      -> Layer 1, one call, no discovery
"who hasn't submitted PS3"  -> Layer 1, one call
"bulk-update SIS section    -> Layer 2 finds POST /accounts/{id}/sis_imports
 codes for my tutorial"     -> Layer 3 executes it
```

### Role handling

Role is detected from the token, not configured. On first use the server calls
`GET /v1/users/{id}` (`id=self`) and `GET /v1/users/{user_id}/enrollments`
(`user_id=self`), yielding per-course role (`student`, `ta`, `teacher`, `designer`,
`observer`). Cached for the process lifetime.

All tools register regardless of role. A student calling `grade_submission` receives
Canvas's 403 translated into a plain-language explanation naming their actual role in
that course. Rationale: role varies *per course* — the same user is commonly a student in
one course and a TA in another — so a process-wide role flag would be wrong more often
than right.

### Write posture

Writes are first-class and ungated, per explicit decision. There is no `ENABLE_WRITES`
flag and no `confirm=` parameter. The checkpoint is the MCP client's own per-tool
approval prompt.

Because that prompt is the only checkpoint, it must be readable at the moment it appears.
Therefore, mandatory for every write tool:

- `ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False)`
- Tool description states the concrete effect in its first sentence
  (e.g. "Submits work to Canvas. This is recorded against the deadline and is visible to
  the instructor immediately.")
- `canvas_request` sets `destructiveHint=True` whenever `method != "GET"`

## Module layout

```
canvas-api-mcp/
  pyproject.toml
  README.md
  LICENSE                       MIT
  env.template
  src/canvas_api_mcp/
    __init__.py
    server.py                   FastMCP app, tool registration, entrypoint
    config.py                   env parsing, validation, startup diagnostics
    client.py                   auth, pagination, rate limiting, retries, errors
    catalog.py                  spec fetch/parse/search
    identity.py                 whoami + per-course role, cached
    extract.py                  PDF/PPTX/DOCX -> text
    tools/
      orientation.py
      student.py
      content.py
      discussions.py
      educator.py
      gateway.py
    resources.py
    prompts.py
  data/
    catalog.json                pre-built fallback catalog
  scripts/
    build_catalog.py            regenerate catalog from any Canvas instance
  tests/
    test_client.py
    test_catalog.py
    test_contracts.py
    fixtures/
```

Each module has one responsibility and is independently testable. `client.py` knows
nothing about Canvas semantics; `tools/*` know nothing about HTTP.

### client.py

The foundation every tool goes through.

- **Auth:** `Authorization: Bearer {CANVAS_TOKEN}` on every request.
- **Pagination:** Canvas paginates nearly everything via RFC 5988 `Link` headers with
  `rel="next"`. The client auto-follows to a configurable cap (default 10 pages) and
  reports truncation explicitly in the result rather than silently returning partial data.
- **Rate limiting:** Canvas uses a leaky-bucket quota and returns `X-Rate-Limit-Remaining`.
  The client throttles as that value approaches zero and backs off on the 403
  "Rate Limit Exceeded" response, which is distinguished from a genuine permission 403 by
  inspecting the body.
- **Retries:** exponential backoff on 429 and 5xx; no retry on 4xx.
- **Error translation:** every Canvas error becomes an actionable message.
  - `401` -> token invalid or expired; how to mint a new one
  - `403` -> insufficient permission, naming the user's actual role in that course
  - `404` -> not found, or exists but not visible to this user

### catalog.py

Builds and searches the endpoint catalog.

`scripts/build_catalog.py` takes any Canvas base URL, fetches `/doc/api/api-docs.json`,
downloads each listed resource file, flattens every operation to
`{family, method, path, nickname, summary, parameters}`, and writes `catalog.json`.

A pre-built catalog generated from NUS ships in `data/`. Because every Canvas instance
serves its own spec, users at other institutions can regenerate to match their own
deployment's version and enabled feature set. Catalog rebuilds require no code changes.

`search_canvas_api` ranks by keyword overlap across nickname, summary, and path, with an
optional method filter.

## Tool surface

Write tools marked ✏️.

### Orientation (2)

| Tool | Endpoints |
|---|---|
| `whoami` | `GET /v1/users/{id}`, `GET /v1/users/{user_id}/enrollments` |
| `my_courses` | `GET /v1/courses` |

### Student (7)

| Tool | Endpoints |
|---|---|
| `whats_due` | `GET /v1/users/self/todo`, `GET /v1/users/self/upcoming_events`, `GET /v1/planner/items` |
| `my_grades` | `GET /v1/courses/{course_id}/enrollments` |
| `list_assignments` | `GET /v1/courses/{course_id}/assignments` |
| `get_assignment` | `GET /v1/courses/{course_id}/assignments/{id}` |
| `my_submission` | `GET /v1/courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}` |
| `submit_assignment` ✏️ | `POST /v1/courses/{course_id}/assignments/{assignment_id}/submissions` |
| `course_announcements` | `GET /v1/announcements` |

### Content (4)

| Tool | Endpoints |
|---|---|
| `course_content` | `GET /v1/courses/{course_id}/modules` + module items |
| `list_files` | `GET /v1/courses/{course_id}/files` |
| `read_file` | `GET /v1/files/{id}` + download + text extraction |
| `get_page` | `GET /v1/courses/{course_id}/pages/{url_or_id}` |

### Discussions (2)

| Tool | Endpoints |
|---|---|
| `read_discussion` | `GET /v1/courses/{course_id}/discussion_topics`, `.../{topic_id}/view` |
| `post_discussion_reply` ✏️ | `POST /v1/courses/{course_id}/discussion_topics/{topic_id}/entries` |

### Educator (7)

| Tool | Endpoints |
|---|---|
| `course_roster` | `GET /v1/courses/{course_id}/users` |
| `submission_queue` | `GET /v1/courses/{course_id}/students/submissions` |
| `get_submissions` | `GET /v1/courses/{course_id}/assignments/{assignment_id}/submissions` |
| `grade_submission` ✏️ | `PUT /v1/courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}` |
| `bulk_grade` ✏️ | `POST /v1/courses/{course_id}/assignments/{assignment_id}/submissions/update_grades` |
| `post_announcement` ✏️ | `POST /v1/courses/{course_id}/discussion_topics` (`is_announcement=true`) |
| `grant_extension` ✏️ | `POST /v1/courses/{course_id}/assignments/{assignment_id}/overrides` |

`at_risk_students` (`GET /v1/courses/{course_id}/analytics/student_summaries`) is reachable
via the gateway rather than curated, since Canvas Analytics is disabled at some
institutions and a curated tool that frequently 404s is worse than no tool.

### Gateway (2)

| Tool | Behaviour |
|---|---|
| `search_canvas_api` | Ranked endpoint search over the catalog; optional method filter |
| `canvas_request` ✏️ | Executes any endpoint. `dry_run=True` returns the prepared request without sending |

All endpoint mappings above were verified against the catalog extracted from
`canvas.nus.edu.sg` on 2026-08-07.

## Resources

| URI | Contents |
|---|---|
| `canvas://me` | Identity and per-course roles |
| `canvas://courses` | Active courses with term and role |
| `canvas://api/catalog` | Full endpoint catalog |

## Prompts

| Prompt | Purpose |
|---|---|
| `grading_triage` | Pull ungraded queue, cluster failure modes, draft per-student feedback for review before writing back |
| `week_ahead` | Merge deadlines with submission state, rank by urgency and weight |
| `study_pack` | Gather modules, pages, and files for a topic into a study set |

These are the workflow layer, and the natural seed for Agent Skills later.

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `CANVAS_BASE_URL` | yes | e.g. `https://canvas.nus.edu.sg` |
| `CANVAS_TOKEN` | yes | Personal access token |
| `CANVAS_MAX_PAGES` | no | Pagination cap, default 10 |

Supplied via the MCP client's `env` block. On startup, missing or malformed config fails
with an actionable message naming the variable and how to obtain a token.

## Testing

Educator and admin endpoints cannot be exercised live — the author holds a student token,
so every teacher call returns 403. Coverage is therefore split:

- **Contract tests** (`test_contracts.py`) — generated from the catalog. For every curated
  tool, assert the request the tool constructs matches the spec: correct method, correct
  path template, required parameters present, parameter types valid. Verifies the educator
  half by construction without a teacher token.
- **Fixture tests** (`test_client.py`) — recorded Canvas responses covering `Link`-header
  pagination, rate-limit backoff, and each error-translation branch.
- **Catalog tests** (`test_catalog.py`) — parse and search behaviour against a checked-in
  spec sample.
- **Live smoke tests** — real calls against the author's student token, skipped unless
  `CANVAS_LIVE_TESTS=1`, never run in CI.

`dry_run` on `canvas_request` doubles as a manual verification path for write endpoints.

## Distribution

- GitHub, MIT licence, issues and PRs open.
- PyPI as `canvas-api-mcp`; primary install path is `uvx canvas-api-mcp`, which requires no
  prior install step.
- stdio transport by default. `--transport http` exists for users who want to self-host
  behind their own auth, documented as an advanced option and not the recommended path.
- README carries copy-paste config blocks for Claude Code, Claude Desktop, Cursor, and
  Continue.

## Risks

**Institutions may disable student token generation.** Confirmed **available** at NUS on
2026-08-07 — `+ New access token` is present under Approved Integrations for a student
account, so the bearer-token design is viable on the first target instance. This remains a
risk at other institutions: where token generation is disabled, no bearer-token design
works and the only fallback is browser automation driving an authenticated session —
substantially worse, and out of scope for this spec. The README must state this
prerequisite plainly so prospective users can check before installing.

Canvas allows an optional expiry when minting a token. The README should recommend setting
a term-length expiry rather than accepting "never", to bound the blast radius of a leak.

**A Canvas token is equivalent to full account access.** It can read grades and private
instructor messages and submit work. It is stored in plaintext in the MCP client config
per explicit decision. The README must state this so users at other institutions can make
their own call.

**Analytics and some features are per-institution.** Endpoints present in the spec may
still 404 where a feature is disabled. Error translation must distinguish "not found" from
"not enabled here."

## Open decisions

None. Naming (`canvas-api-mcp`), storage (client `env` block), write posture (ungated),
and architecture (three-layer) are settled.
