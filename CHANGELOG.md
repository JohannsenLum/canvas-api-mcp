# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.4] - 2026-08-09

### Fixed

- **`read_discussion` no longer crashes on deeply nested reply chains.** `_flatten`
  recursed once per nesting level, so a thread nested past Python's recursion limit
  raised `RecursionError` and the whole tool call died. The measured ceiling was 997
  replies. That is reachable in practice, because students reply to the latest message
  rather than the root, which builds a deep chain rather than wide siblings, and it
  failed hardest on the busiest threads. Now traverses with an explicit stack, so the
  limit is memory rather than 997. Contributed by @jiahao6635 in #31, closing #15.

### Changed

- **Every em-dash removed** from tool descriptions, error messages, prompts and
  documentation. Some of these strings are user-visible, which is why this is a
  release rather than a tidy-up. No wording changed meaning.

### Added

- `CODE_OF_CONDUCT.md`, carrying two rules specific to this project: never post a real
  access token, calendar feed URL or signed download link, and never include another
  person's Canvas data in a bug report.

### Docs

- `CONTRIBUTING.md` told contributors to run `scripts/build_catalog.py`, which stopped
  being the entry point in 0.0.3 when regeneration moved inside the package. Documents
  `canvas-api-mcp-build-catalog` and the catalog resolution order instead.

## [0.0.3] - 2026-08-08

Three of these are credential-handling fixes. None were exploited, and none
required a leaked secret to have already happened, but two of them put a
password-equivalent value somewhere it did not belong, so upgrading is worth
doing.

### Security

- **Pagination no longer follows a `Link` header to another host.** The
  `rel="next"` URL comes from the server, and every request the client sends
  carries the `Authorization` header, so a `Link` header naming a third party
  would have handed it your Canvas access token, which is password-equivalent.
  `_normalise_path` already blocked this for caller-supplied paths; the guard
  simply did not extend to pagination, the one place a URL enters the client
  from outside. Off-origin links are now refused and reported as truncation.
  Relative links still resolve normally.
- **`whoami` no longer returns `calendar_feed_url`.** The `.ics` link is a bearer
  credential: holding it is enough to read your entire Canvas calendar with no
  authentication, and it does **not** expire when you rotate your access token.
  `whoami` is the call-this-first orientation tool, so that value was landing in
  conversation context, and client logs, at the start of every session. It now
  lives behind `get_calendar_feed_url`, fetched only when asked for. (#13)
- **`read_file` no longer echoes the signed download URL in its errors.** Canvas
  file links carry a `verifier` query parameter that authenticates the download
  on its own. Interpolating the raw `httpx` exception into the error message put
  that verifier into the tool's output. Errors now report the status code and an
  actionable hint instead. (#16, reported and fixed by @IzzaldinSamir in #25)

### Added

- **`get_calendar_feed_url` tool.** Returns the private `.ics` subscription link
  you can add to Google, Apple or Outlook calendar to see Canvas deadlines
  natively, fetched fresh per call rather than cached, so it cannot outlive a
  token rotation, and returned with an explicit warning that it is a credential.
  The underlying endpoint switch came from @basil-boh in #12. (#13)
- **`canvas-api-mcp-build-catalog` console script.** Institutions run different
  Canvas versions with different endpoints, so the bundled 1,116-endpoint catalog
  is a sensible default rather than the truth, but regeneration lived outside the
  wheel, so anyone who installed with `pip` or `uvx` could not run it at all.
  `load_catalog` now resolves an explicit path, then `CANVAS_CATALOG_PATH`, then
  `~/.cache/canvas-api-mcp/catalog.json`, then the bundled default, so running the
  command once is enough for your school's catalog to take over. (#9)

### Fixed

- **A total Canvas outage is no longer reported as "nothing due".** `whats_due`
  degrades gracefully when one source fails, which is correct, but when *every*
  source failed it returned a clean empty list, and a student was told they had
  nothing due when the truth was that Canvas was unreachable. It now returns an
  explicit error with no `items` key at all, so an empty result cannot be mistaken
  for a real answer. (#20)
- **Transport failures produce an actionable error.** A bad `CANVAS_BASE_URL`, DNS
  failure, refused connection or timeout raises `httpx.ConnectError` and friends,
  none of which are `HTTPStatusError`, so they escaped as raw tracebacks. They are
  now translated into a `CanvasError` that names `CANVAS_BASE_URL` explicitly. (#19)
- **`read_file` returns a structured error when a download fails.** Every other
  failure path honoured the tool's `{"error": true, ...}` contract; the raw file
  download called `raise_for_status()` bare. Canvas file URLs are time-limited, so
  403-on-expiry and 404-on-delete are the normal ways that call fails, not edge
  cases. (#16, #25)

### Changed

- `whoami`'s output no longer contains `calendar_feed_url`. If you read that field,
  call `get_calendar_feed_url` instead. Its `login_id` fix from 0.0.2 is unchanged.

## [0.0.2] - 2026-08-08

### Fixed

- **`whats_due` now honours the `days` horizon.** It accepted the parameter, echoed it
  back, and filtered nothing: a request for 1 day returned items due a year out.
  Canvas applies its own horizons to `/todo`, `/upcoming_events` and `/planner/items`,
  and they agree neither with each other nor with the caller. Reported by
  @jiahao6635 in #11. Undated work is kept and flagged `undated: true` rather than
  dropped, since a to-do with no due date is still outstanding.
- **`canvas_request` can reach Canvas GraphQL.** `_normalise_path` prefixed `/api/v1`
  unconditionally, so `/api/graphql` became `/api/v1/graphql`. Paths already under
  `/api` now pass through untouched. (#1)
- **The missing-token error names your own Canvas.** It printed a literal
  `<your-canvas>` placeholder instead of substituting `CANVAS_BASE_URL`.

### Security

- `_normalise_path` now rejects absolute URLs of any scheme, `..` traversal, CR/LF
  (header smuggling), backslashes, and empty input. This is the one place a
  caller-supplied string becomes the URL a request is sent to, and `canvas_request`
  accepts arbitrary paths from a model while a bearer token rides on every request.

### Changed

- `whoami` reads `GET /users/self/profile` instead of `GET /users/self` (strictly the
  richer endpoint) and returns `calendar_feed_url`. Contributed by @basil-boh in #12.
  Note that the `.ics` URL is credential-bearing; moving it out of `whoami` is tracked
  in #13.
- Windows and Linux client config paths documented, stating only what could be verified
  against each client's own docs. (#5)

### Added

- Animated terminal header demonstrating the gateway resolving a question no curated
  tool covers.
- `SECURITY.md`, `CONTRIBUTING.md`, issue and pull-request templates, and `examples/`
  with validated per-client configs.

### Tests

- 126, up from 97.

### Added

- `whoami` now returns `calendar_feed_url`: the user's private Canvas calendar .ics
  link, so the user can subscribe to every Canvas deadline in Google/Apple/Outlook
  calendar directly, without any further tool calls.

### Fixed

- `whoami`'s `login_id` was always `None` in production. `identity.py` fetched
  `GET /users/self`, which does not carry `login_id` on this Canvas deployment; only
  `GET /users/self/profile` does. Switching to `/profile` fixes `login_id` and is also
  where `calendar_feed_url` (above) comes from.

## [0.0.1] - 2026-08-07

First release. Student-scoped, personal use. Early software: the version
number is deliberate.

### Added

- **17 MCP tools**: 15 curated plus a 2-tool gateway reaching all 1,116 endpoints on a
  stock Instructure Canvas deployment.
  - Orientation: `whoami`, `my_courses`
  - Student: `whats_due`, `my_grades`, `list_assignments`, `get_assignment`,
    `my_submission`, `submit_assignment`, `course_announcements`
  - Content: `course_content`, `list_files`, `read_file`, `get_page`
  - Discussions: `read_discussion`, `post_discussion_reply`
  - Gateway: `search_canvas_api`, `canvas_request`
- **3 prompts**: `week_ahead`, `study_pack`, `grade_check`.
- **3 resources**: `canvas://me`, `canvas://courses`, `canvas://api/catalog`.
- **3 Agent Skills**: `canvas-week-plan`, `canvas-study-pack`, `canvas-grade-check`,
  installable with `npx skills add JohannsenLum/canvas-api-mcp`.
- **Endpoint catalog** generated from a Canvas instance's own OpenAPI spec, so it
  matches that deployment's version and enabled features. Regenerate with
  `scripts/build_catalog.py`.
- **RFC 5988 `Link`-header pagination** with explicit truncation reporting: partial
  results are never returned silently.
- **Rate-limit throttling** against Canvas's published quota, plus retries with
  exponential backoff on 429 and 5xx only.
- **Error translation**: 401/403/404/5xx become actionable messages, and a rate-limit
  403 is distinguished from a permission 403 by inspecting the response body.
- Text extraction from PDF, DOCX, PPTX, and plain text in `read_file`.
- 97 tests, plus live smoke tests gated behind `CANVAS_LIVE_TESTS=1`.

### Security

- `read_file` fetches Canvas's pre-signed download URLs with a bare HTTP client that
  carries no `Authorization` header, so the bearer token is never sent to the file host.
- Write tools (`submit_assignment`, `post_discussion_reply`, and `canvas_request` with a
  non-GET method) carry `destructiveHint=True` and state their concrete effect in the
  first sentence of their description, so the client's approval prompt is readable.
- Configuration rejects a non-HTTPS `CANVAS_BASE_URL`.

### Known limitations

- No curated educator tools. Educator endpoints are reachable via the gateway with a
  teacher token; curated ergonomics are deferred. See `docs/DESIGN.md`.
- Personal use only. Canvas's API Policy requires OAuth for multi-user applications, and
  Canvas OAuth supports neither PKCE nor public clients, so locally-installed software
  cannot implement it safely. See the Compliance section of the README.
- `canvas_request` cannot reach Canvas's GraphQL API. `_normalise_path` prefixes every
  path with `/api/v1`, so `/api/graphql` becomes `/api/v1/graphql` and 404s. REST is
  unaffected. Tracked in the issue tracker.
- No `init` command yet. Setup means creating a token and editing your MCP client's
  config by hand: see the install guide at
  <https://mcp.johannsenlum.com/canvas-lms/install>.

[Unreleased]: https://github.com/JohannsenLum/canvas-api-mcp/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/JohannsenLum/canvas-api-mcp/releases/tag/v0.0.2
[0.0.1]: https://github.com/JohannsenLum/canvas-api-mcp/releases/tag/v0.0.1
