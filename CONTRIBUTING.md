# Contributing

Issues and pull requests are welcome. This is a personal project run by a student, so
reviews may take a few days.

## Getting set up

```bash
git clone https://github.com/JohannsenLum/canvas-api-mcp
cd canvas-api-mcp
uv sync --extra dev
uv run pytest -q          # 97 tests, ~5 seconds
```

Live tests hit a real Canvas account and are skipped by default. To run them you need
your own token:

```bash
CANVAS_LIVE_TESTS=1 \
CANVAS_BASE_URL=https://canvas.yourschool.edu \
CANVAS_TOKEN=your-token \
uv run pytest tests/test_live.py -v
```

They are read-only apart from a `dry_run` that sends nothing. Never add a live test
that writes to Canvas.

## How the code is organised

```
src/canvas_api_mcp/
  client.py      auth, Link-header pagination, rate limiting, error translation
  config.py      environment parsing and validation
  catalog.py     search over the 1,116-endpoint catalog
  identity.py    whoami + per-course role, cached
  extract.py     PDF / DOCX / PPTX / text extraction
  tools/         one module per tool group
  server.py      FastMCP app and entrypoint
```

Two rules that are load-bearing:

- **Tools never construct HTTP requests.** Everything goes through `client.py`. That is
  where auth, pagination, throttling, and error translation live, and it is the only
  place they should live.
- **The server never simulates permissions.** Canvas decides what a token may do. Do not
  add checks that pre-filter calls based on a user's role — surface Canvas's answer
  instead. A 403 with a clear message is correct behaviour.

See [docs/DESIGN.md](docs/DESIGN.md) for why the architecture is three layers and why
phase 1 is student-scoped.

## Pull requests

- **Write a failing test first.** Every existing feature was built that way and the
  suite is the reason changes are safe.
- **Keep `uv run pytest` green.** CI runs it on Python 3.11 and 3.12.
- **Do not weaken rate limiting.** The throttle in `client.py` is a compliance
  requirement, not a performance knob.
- **Write tools must stay honest.** `submit_assignment`, `post_discussion_reply`, and
  `canvas_request` carry `destructiveHint=True` and state their effect in the first
  sentence of their description. That first sentence is what a user sees in an approval
  prompt — it is the whole safety mechanism.
- **No curated educator tools yet.** Phase 1 is student-scoped for the reasons in
  DESIGN.md. Educator endpoints are already reachable through the gateway.

## Adding a tool

Only add a curated tool if it answers a question people actually ask often. Anything
rarer is already reachable via `search_canvas_api` + `canvas_request`, and every added
tool costs context on every turn for every user.

If you do add one:

1. Check the endpoint exists in `canvas_api_mcp/data/catalog.json`.
2. Write the test first, against fixtures — not a live account.
3. Put it in the matching `tools/` module and register it in `server.py`.
4. Give it accurate `ToolAnnotations`.
5. Update the tool table in `README.md`.

## Regenerating the endpoint catalog

Every Canvas instance serves its own API spec, so the catalog can be rebuilt to match
any deployment. From a source checkout:

```bash
uv run canvas-api-mcp-build-catalog https://canvas.yourschool.edu \
  -o src/canvas_api_mcp/data/catalog.json
```

The same command ships with the installed package, so users who never clone the repo
can regenerate against their own institution too:

```bash
canvas-api-mcp-build-catalog https://canvas.yourschool.edu
```

With no `-o`, it writes to `~/.cache/canvas-api-mcp/catalog.json`, which `load_catalog`
prefers over the bundled default. Resolution order is: explicit path, then
`CANVAS_CATALOG_PATH`, then that cache file, then the catalog shipped in the wheel.

## Reporting bugs

Use the issue templates — they ask for the Canvas instance, Python version, and MCP
client, which are the three things needed to reproduce anything.

Security problems go through [SECURITY.md](SECURITY.md), not public issues.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). It carries
two rules specific to this project, both about other people's data: never post a real
access token, calendar feed URL, or signed download link, and never include another
person's Canvas data in a bug report.
