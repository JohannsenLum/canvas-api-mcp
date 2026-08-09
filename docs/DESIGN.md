# canvas-api-mcp: Design

**Date:** 2026-08-07
**Status:** Approved design, pending implementation plan

## Goal

An MCP server that lets any AI agent read and act on a user's own Canvas LMS account.

**Phase 1 (this spec): student use.** Curated tools cover a student's own data only. The
author is the first user (NUS student); peers at NUS are the first distribution target.
Open source (MIT), built to accept forks and pull requests.

Scoping to students first is deliberate. A student token reaches only that student's own
data, which removes third-party personal-data handling from the design entirely, and makes
every tool live-testable by the author. See Compliance.

## Non-goals

- **No curated educator tools in phase 1.** Not a capability limitation: Canvas enforces
  permissions server-side per token, so the gateway layer already reaches every educator
  endpoint and will work for anyone holding a teacher token. Curated educator tools are an
  ergonomics layer, deferred to phase 2 (see Roadmap).
- **No hosted/shared deployment.** Every user runs their own local process with their own
  token. Hosting would mean custodying other people's Canvas credentials: high liability,
  no offsetting benefit.
- **No institution-specific hardcoding.** NUS is the first test instance, not the target.
- **Not competing on curated-tool count** with existing Canvas MCP servers. The tool
  surface is deliberately small; completeness comes from the gateway.

## Background

NUS runs a stock Instructure Canvas instance at `https://canvas.nus.edu.sg`, behind SAML
SSO (`/login/saml/210`). SSO gates *browser* login only; the REST API authenticates
separately via bearer token, so no SAML handling is needed. Student personal access token
generation was confirmed enabled on 2026-08-07.

The instance serves its own machine-readable spec (Swagger 1.2) at `/doc/api/api-docs.json`,
enumerating 143 resource files. Extracting all of them yields the authoritative endpoint
map for that exact deployment:

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
2. The long tail is genuinely needed but unpredictable.

Exposing 1,116 endpoints as 1,116 tools is not viable: tool-selection accuracy degrades as
the list grows, and every tool schema costs context on every turn. Exposing only a curated
subset permanently orphans the long tail and requires hand-writing a new tool each time
Instructure ships an endpoint.

## Architecture

Three layers.

**Layer 1: Curated tools (16).** Named after jobs, not endpoints. Carry real ergonomics:
`whats_due()` fans out to multiple endpoints and merges results, because that is what the
question means.

**Layer 2: Discovery.** `search_canvas_api(query)` ranks matches over an embedded catalog
of all 1,116 endpoints (method, path, nickname, summary, parameters).

**Layer 3: Passthrough.** `canvas_request(method, path, params, body, dry_run)` executes
any endpoint the search surfaces, subject to whatever the caller's token permits.

Result: complete API reach at 18 tool schemas (16 curated + 2 gateway).

```
"what's due this week"      -> Layer 1, one call, no discovery
"my grade breakdown"        -> Layer 1, one call
"list my group memberships" -> Layer 2 finds GET /users/self/groups
                            -> Layer 3 executes it
```

### Permission model

Authorisation is Canvas's job, not the server's. Every request carries the user's token and
Canvas decides what it permits. The server never simulates, predicts, or pre-filters
permissions: it surfaces Canvas's answer.

The server still detects identity for *ergonomics*: on first use it calls
`GET /v1/users/{id}` (`id=self`) and `GET /v1/users/{user_id}/enrollments`
(`user_id=self`), yielding per-course role (`student`, `ta`, `teacher`, `designer`,
`observer`), cached for the process lifetime. This is used to write better error messages
and to let agents orient, not to gate calls.

Consequence: the same binary serves educators through the gateway the moment a teacher
token is used, with no code change.

### Write posture

Writes are first-class and ungated, per explicit decision. There is no `ENABLE_WRITES` flag
and no `confirm=` parameter. The checkpoint is the MCP client's own per-tool approval
prompt.

Because that prompt is the only checkpoint, it must be readable at the moment it appears.
Mandatory for every write tool:

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
    test_tools.py
    fixtures/
```

Each module has one responsibility and is independently testable. `client.py` knows nothing
about Canvas semantics; `tools/*` know nothing about HTTP.

### client.py

The foundation every tool goes through.

- **Auth:** `Authorization: Bearer {CANVAS_TOKEN}` on every request. The header is produced
  in one place so an OAuth2 token source can replace it in phase 2 without touching callers.
- **Pagination:** Canvas paginates nearly everything via RFC 5988 `Link` headers with
  `rel="next"`. The client auto-follows to a configurable cap (default 10 pages) and reports
  truncation explicitly rather than silently returning partial data.
- **Rate limiting:** Canvas uses a leaky-bucket quota and returns `X-Rate-Limit-Remaining`.
  The client throttles as that value approaches zero and backs off on the 403 "Rate Limit
  Exceeded" response, distinguished from a genuine permission 403 by inspecting the body.
  This is a compliance requirement, not an optimisation: see Compliance.
- **Retries:** exponential backoff on 429 and 5xx; no retry on 4xx.
- **Error translation:** every Canvas error becomes an actionable message.
  - `401` -> token invalid or expired; how to mint a new one
  - `403` -> insufficient permission, naming the user's actual role in that course
  - `404` -> not found, or exists but not visible to this user, or feature not enabled at
    this institution

### catalog.py

`scripts/build_catalog.py` takes any Canvas base URL, fetches `/doc/api/api-docs.json`,
downloads each listed resource file, flattens every operation to
`{family, method, path, nickname, summary, parameters}`, and writes `catalog.json`.

A pre-built catalog generated from NUS ships in `data/`. Because every Canvas instance
serves its own spec, users elsewhere can regenerate to match their deployment's version and
enabled feature set. Catalog rebuilds require no code changes.

`search_canvas_api` ranks by keyword overlap across nickname, summary, and path, with an
optional method filter.

## Tool surface

Write tools marked ✏️. All endpoint mappings verified against the catalog extracted from
`canvas.nus.edu.sg` on 2026-08-07.

### Orientation (3)

| Tool | Endpoints |
|---|---|
| `whoami` | `GET /v1/users/self/profile`, `GET /v1/users/{user_id}/enrollments` |
| `get_calendar_feed_url` | `GET /v1/users/self/profile` |
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

### Gateway (2)

| Tool | Behaviour |
|---|---|
| `search_canvas_api` | Ranked endpoint search over the catalog; optional method filter |
| `canvas_request` ✏️ | Executes any endpoint, subject to token permissions. `dry_run=True` returns the prepared request without sending |

## Resources

| URI | Contents |
|---|---|
| `canvas://me` | Identity and per-course roles |
| `canvas://courses` | Active courses with term and role |
| `canvas://api/catalog` | Full endpoint catalog |

## Prompts

| Prompt | Purpose |
|---|---|
| `week_ahead` | Merge deadlines with submission state, rank by urgency and weight |
| `study_pack` | Gather modules, pages, and files for a topic into a study set |
| `grade_check` | Compute standing in a course and what remaining work is worth |

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

Because phase 1 is student-scoped, every tool is exercisable with the author's own token.
No mock-only surface.

- **Unit tests** (`test_client.py`): recorded Canvas responses covering `Link`-header
  pagination, rate-limit backoff, and each error-translation branch.
- **Catalog tests** (`test_catalog.py`): parse and search behaviour against a checked-in
  spec sample.
- **Tool tests** (`test_tools.py`): each tool's request construction and response shaping,
  against fixtures.
- **Live smoke tests**: real calls against the author's student token, skipped unless
  `CANVAS_LIVE_TESTS=1`, never run in CI. Read-only; write tools are verified via `dry_run`.

## Compliance

Instructure's OAuth2 documentation states that manually generated personal access tokens
are intended for testing, that "asking any other user to manually generate a token and enter
it into your application is a violation of Canvas' API Policy," and that "applications in
use by multiple users MUST use OAuth to obtain tokens."

This produces a hard boundary in the project's rollout:

| Activity | Position |
|---|---|
| Author using their own token on their own data | Sanctioned, the documented use of manual tokens |
| Publishing source code | Fine |
| Instructing other users to mint tokens and paste them | **Contravenes Canvas API Policy** |

**Therefore: phase 1 is for personal use and source publication only.** Publishing source is
unaffected: code is not a Canvas integration until someone runs it. General distribution
requires an answer to how other users authenticate, which is not purely a coding decision;
see Roadmap.

Tokens never reach the author under any configuration: each user's token stays in their own
MCP client config on their own machine. This removes credential-custody risk but does not
resolve the policy point above, which concerns the instruction to mint tokens, not their
storage location.

Other obligations reflected in the design:

- **Rate limiting**: the API Policy prohibits interfering with or overloading systems. The
  client's `X-Rate-Limit-Remaining` throttling is a compliance requirement and must not be
  removed or made optional.
- **Academic integrity**: the API Policy prohibits use violating academic integrity
  policies. `submit_assignment` is the relevant surface; the README must carry an explicit
  note that submitting AI-generated work may breach institutional rules.
- **Copyright**: `read_file` retrieves course materials for the user's own study. The tool
  must not cache to a shared location, and the README must not encourage redistribution.
- **Personal data**: a student token reaches only the user's own data, so no third-party
  personal data is processed in phase 1. This changes in phase 2 and must be revisited then,
  including Singapore PDPA obligations and NUS data-classification rules for transferring
  student data to external AI services.

Not legal advice. NUS IT should be consulted before distribution.

## Roadmap

**Phase 1 (this spec)**: student-scoped curated tools, gateway, personal use.

**Phase 2: distribution.** Blocked on an authentication answer, not on code.

Canvas OAuth2 does not support PKCE or public clients. Verified against
`instructure/canvas-lms:doc/api/oauth.md` and `doc/api/oauth_endpoints.md`: no
`code_challenge`, `code_verifier`, or public-client handling appears in either file, and
`client_secret` is required for the token exchange. Locally installed software therefore
cannot implement Canvas OAuth without embedding an extractable `client_secret` in every
copy, worse than personal tokens, not better.

The remaining options, none of which the author can choose unilaterally:

| Option | Requires |
|---|---|
| Institution-issued developer key, configured per install | An NUS Canvas admin to issue a key and accept the shared-secret model |
| Hosted service holding the secret | Operating infrastructure and custodying credentials, rejected in Non-goals |
| Continue with personal tokens | Accepting that this contravenes the API Policy sentence on instructing users to mint tokens |

Next action is to ask NUS IT how they would prefer students to use this, rather than to pick
an approach and present it as settled.

**Phase 3: educator support.** Curated grading and course-management tools. Gated on phase
2 plus a PDPA and NUS data-governance review, because educator use processes other people's
personal data.

**Documentation site.** The repository will publish a docs site to Vercel via its GitHub
integration; domain to be chosen by the author. Independent of the server design and not a
prerequisite for any phase.

Phase 1 is designed so later phases are additive: the `Authorization` header is produced in
one place in `client.py`, so an alternative token source replaces it without touching any
caller, and educator endpoints are already reachable via the gateway.

## Risks

**Distribution is blocked on OAuth2.** Phase 1 must not be promoted to other users. The
README must state that it is personal-use software pending a developer key.

**Institutions may disable student token generation.** Confirmed available at NUS on
2026-08-07. Remains a prerequisite elsewhere; the README must say so.

**A Canvas token is equivalent to full account access.** It can read grades and private
instructor messages and submit work. It is stored in plaintext in the MCP client config per
explicit decision. The README must state this, and recommend setting a term-length token
expiry rather than accepting "never".

**Features vary per institution.** Endpoints present in the spec may 404 where a feature is
disabled. Error translation must distinguish "not found" from "not enabled here."

## Open decisions

None. Naming (`canvas-api-mcp`), storage (client `env` block), write posture (ungated),
architecture (three-layer), and phase-1 scope (student-only, personal use) are settled.
