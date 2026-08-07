<!-- mcp-name: io.github.JohannsenLum/canvas-api-mcp -->

# canvas-api-mcp

An MCP server for Canvas LMS. 15 curated tools for everyday student work, plus a
gateway that reaches every endpoint your Canvas instance exposes.

**📖 Documentation: [mcp.johannsenlum.com/canvas-lms](https://mcp.johannsenlum.com/canvas-lms)**
— [install guide](https://mcp.johannsenlum.com/canvas-lms/install) ·
[tool reference](https://mcp.johannsenlum.com/canvas-lms/tools) ·
[skills](https://mcp.johannsenlum.com/canvas-lms/skills) ·
[compliance](https://mcp.johannsenlum.com/canvas-lms/compliance)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/JohannsenLum/canvas-api-mcp/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/JohannsenLum/canvas-api-mcp?style=social)](https://github.com/JohannsenLum/canvas-api-mcp)
<!-- Once canvas-api-mcp is published to PyPI, add and verify it renders green (not a 404 "not found" badge):
[![PyPI](https://img.shields.io/pypi/v/canvas-api-mcp)](https://pypi.org/project/canvas-api-mcp/) -->

> **Personal-use software.** Canvas's API Policy requires OAuth for applications used
> by multiple people, and Canvas OAuth cannot be implemented safely by locally
> installed software (no PKCE, and `client_secret` cannot be shipped in a package).
> Use this with your own token on your own account. See [Compliance](#compliance).

## What you can ask it

Real prompts, and which tool answers them.

> **You:** What's due this week?
> **Claude:** *(calls `whats_due`)* — You have 3 things due: Problem Set 4 (Thu,
> CS3230), a discussion reply (Fri, IS4302), and the Milestone 2 report (Sun,
> EE2211).

> **You:** How am I doing in my databases course, and what's on the syllabus for
> week 6?
> **Claude:** *(calls `my_grades`, then `get_page` for the syllabus, then
> `course_content` for the week 6 module)* — You're at 87% overall. Week 6 covers
> normalization and has a reading plus a lab file due Friday.

> **You:** Summarize the PDF lecture notes for lecture 8 and pull up my submission
> for the essay so I can see the feedback.
> **Claude:** *(calls `list_files` + `read_file` for the PDF, then `my_submission`
> for the essay)* — ...

> **You:** Reply to the "Project teams" discussion and say I'm free after 3pm for
> the group meeting.
> **Claude:** *(calls `post_discussion_reply` ✏️)* — Posted to the thread.

> **You:** Has Canvas ever given me quiz statistics broken down by question, across
> the whole semester?
> **Claude:** *(calls `search_canvas_api` to find the right endpoint, then
> `canvas_request` to call it)* — ...

The last example is the point of the gateway tools: if an endpoint exists on your
Canvas instance, `search_canvas_api` can find it and `canvas_request` can call it,
even though only 15 tools are hand-curated.

## Install

### Prerequisites

- Python 3.11+
- A Canvas personal access token. Your institution must allow students to create
  them: check **Canvas → Account → Settings → Approved Integrations** for a
  **"+ New access token"** button. Full walkthrough with screenshots:
  [mcp.johannsenlum.com/canvas-lms/install](https://mcp.johannsenlum.com/canvas-lms/install).

### Running the server

The PyPI package name `canvas-api-mcp` is reserved but **not yet published**.
Until it is, install straight from GitHub:

```bash
uvx --from git+https://github.com/JohannsenLum/canvas-api-mcp canvas-api-mcp
```

Once published, this shortens to:

```bash
uvx canvas-api-mcp
```

(`uvx canvas-api-mcp` on its own does not work yet — it will 404 against PyPI
until the package ships. Use the `git+` form above until then.)

Or run from a local clone:

```bash
git clone https://github.com/JohannsenLum/canvas-api-mcp
cd canvas-api-mcp
uv sync
```

### Quick install (one-click)

One-click deeplinks exist for Cursor, VS Code, and LM Studio only — no other
client has a documented install-link format. These prefill the config below but
still need `CANVAS_BASE_URL` and `CANVAS_TOKEN` filled in afterward.

[![Add to Cursor](https://img.shields.io/badge/Cursor-Add_MCP_Server-000000?style=flat-square&logo=cursor&logoColor=white)](https://cursor.com/en/install-mcp?name=canvas&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL0pvaGFubnNlbkx1bS9jYW52YXMtYXBpLW1jcCIsImNhbnZhcy1hcGktbWNwIl0sImVudiI6eyJDQU5WQVNfQkFTRV9VUkwiOiJodHRwczovL2NhbnZhcy55b3Vyc2Nob29sLmVkdSIsIkNBTlZBU19UT0tFTiI6InlvdXItdG9rZW4taGVyZSJ9fQ==)
[![Add to VS Code](https://img.shields.io/badge/VS_Code-Install_Server-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=canvas&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22git%2Bhttps%3A%2F%2Fgithub.com%2FJohannsenLum%2Fcanvas-api-mcp%22%2C%22canvas-api-mcp%22%5D%2C%22env%22%3A%7B%22CANVAS_BASE_URL%22%3A%22https%3A%2F%2Fcanvas.yourschool.edu%22%2C%22CANVAS_TOKEN%22%3A%22your-token-here%22%7D%7D)
[![Add to LM Studio](https://img.shields.io/badge/LM_Studio-Add_MCP_Server-6C4FE0?style=flat-square)](lmstudio://add_mcp?name=canvas&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL0pvaGFubnNlbkx1bS9jYW52YXMtYXBpLW1jcCIsImNhbnZhcy1hcGktbWNwIl0sImVudiI6eyJDQU5WQVNfQkFTRV9VUkwiOiJodHRwczovL2NhbnZhcy55b3Vyc2Nob29sLmVkdSIsIkNBTlZBU19UT0tFTiI6InlvdXItdG9rZW4taGVyZSJ9fQ==)

### All clients (manual config)

Your token stays on your machine, in your own config file. It is never
transmitted anywhere except directly to your Canvas instance.

| Client | Deeplink? |
|---|---|
| [Claude Code](#config-claude-code) | no |
| [Claude Desktop](#config-claude-desktop) | no |
| [Cursor](#config-cursor) | yes, above |
| [VS Code](#config-vscode) | yes, above |
| [LM Studio](#config-lmstudio) | yes, above |
| [Zed](#config-zed) | no |
| [Windsurf](#config-windsurf) | no (Windsurf only resolves servers in its own registry) |

<a id="config-claude-code"></a>
<details>
<summary><strong>Claude Code</strong> — <code>~/.claude.json</code></summary>

```jsonc
{
  "mcpServers": {
    "canvas": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/JohannsenLum/canvas-api-mcp",
        "canvas-api-mcp"
      ],
      "env": {
        "CANVAS_BASE_URL": "https://canvas.yourschool.edu",
        "CANVAS_TOKEN": "your-token-here"
      }
    }
  }
}
```

Once published to PyPI, `args` simplifies to `["canvas-api-mcp"]`.
</details>

<a id="config-claude-desktop"></a>
<details>
<summary><strong>Claude Desktop</strong> — <code>claude_desktop_config.json</code></summary>

macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
Windows: `%APPDATA%\Claude\claude_desktop_config.json`

No one-click install exists for Claude Desktop (it installs `.mcpb` bundles, not
deeplinks) — copy this JSON in via **Settings → Developer → Edit Config**:

```jsonc
{
  "mcpServers": {
    "canvas": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/JohannsenLum/canvas-api-mcp",
        "canvas-api-mcp"
      ],
      "env": {
        "CANVAS_BASE_URL": "https://canvas.yourschool.edu",
        "CANVAS_TOKEN": "your-token-here"
      }
    }
  }
}
```
</details>

<a id="config-cursor"></a>
<details>
<summary><strong>Cursor</strong> — <code>~/.cursor/mcp.json</code></summary>

Fallback for the button above, or if you'd rather paste it directly:

```jsonc
{
  "mcpServers": {
    "canvas": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/JohannsenLum/canvas-api-mcp",
        "canvas-api-mcp"
      ],
      "env": {
        "CANVAS_BASE_URL": "https://canvas.yourschool.edu",
        "CANVAS_TOKEN": "your-token-here"
      }
    }
  }
}
```
</details>

<a id="config-vscode"></a>
<details>
<summary><strong>VS Code</strong> — <code>.vscode/mcp.json</code></summary>

Fallback for the button above, or if you'd rather paste it directly. Note VS
Code uses a `servers` key, not `mcpServers`:

```jsonc
{
  "servers": {
    "canvas": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/JohannsenLum/canvas-api-mcp",
        "canvas-api-mcp"
      ],
      "env": {
        "CANVAS_BASE_URL": "https://canvas.yourschool.edu",
        "CANVAS_TOKEN": "your-token-here"
      }
    }
  }
}
```
</details>

<a id="config-lmstudio"></a>
<details>
<summary><strong>LM Studio</strong> — <code>mcp.json</code> (Program → Install → Edit mcp.json)</summary>

Fallback for the button above, or if you'd rather paste it directly:

```jsonc
{
  "mcpServers": {
    "canvas": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/JohannsenLum/canvas-api-mcp",
        "canvas-api-mcp"
      ],
      "env": {
        "CANVAS_BASE_URL": "https://canvas.yourschool.edu",
        "CANVAS_TOKEN": "your-token-here"
      }
    }
  }
}
```
</details>

<a id="config-zed"></a>
<details>
<summary><strong>Zed</strong> — <code>settings.json</code></summary>

No deeplink exists for Zed — add this under `context_servers` in your Zed
settings:

```jsonc
{
  "context_servers": {
    "canvas": {
      "source": "custom",
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/JohannsenLum/canvas-api-mcp",
        "canvas-api-mcp"
      ],
      "env": {
        "CANVAS_BASE_URL": "https://canvas.yourschool.edu",
        "CANVAS_TOKEN": "your-token-here"
      }
    }
  }
}
```
</details>

<a id="config-windsurf"></a>
<details>
<summary><strong>Windsurf</strong> — <code>~/.codeium/windsurf/mcp_config.json</code></summary>

No deeplink exists for Windsurf — it only resolves servers from its own
registry, so this has to be pasted in manually via **Windsurf Settings → MCP
Servers → Edit raw config**:

```jsonc
{
  "mcpServers": {
    "canvas": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/JohannsenLum/canvas-api-mcp",
        "canvas-api-mcp"
      ],
      "env": {
        "CANVAS_BASE_URL": "https://canvas.yourschool.edu",
        "CANVAS_TOKEN": "your-token-here"
      }
    }
  }
}
```
</details>

## Tools

| Tool | What it does |
|---|---|
| `whoami` | Identity, your role in each course, and your calendar feed link |
| `my_courses` | Active courses with code, term, role |
| `whats_due` | Everything due, soonest first |
| `my_grades` | Current score per course |
| `list_assignments` | A course's assignments and submission state |
| `get_assignment` | One assignment in full, with rubric |
| `my_submission` | Your submission, score, and feedback |
| `submit_assignment` ✏️ | Submit work |
| `course_announcements` | Recent announcements |
| `course_content` | Modules and their contents |
| `list_files` | Files in a course |
| `read_file` | Extract text from PDF/DOCX/PPTX/text |
| `get_page` | A Canvas page, e.g. the syllabus |
| `read_discussion` | Topics, or one topic's replies |
| `post_discussion_reply` ✏️ | Post to a discussion |
| `search_canvas_api` | Find any endpoint by keyword (gateway) |
| `canvas_request` ✏️ | Execute any endpoint (gateway) |

✏️ writes to Canvas. That's 3 write tools total: `submit_assignment`,
`post_discussion_reply`, and `canvas_request` when called with a non-GET method
(GET calls through `canvas_request` are read-only).

`search_canvas_api` + `canvas_request` reach all ~1,116 endpoints your instance
exposes. What they may do is decided by Canvas from your token's permissions — a
teacher token unlocks educator endpoints with no change to this server.

## Prompts

`week_ahead`, `study_pack`, `grade_check`.

## Resources

`canvas://me`, `canvas://courses`, `canvas://api/catalog`.

## Skills

If your client supports the [skills](https://github.com/anthropics/skills)
convention:

```bash
npx skills add JohannsenLum/canvas-api-mcp
```

## Other institutions

Works with any Canvas instance — set `CANVAS_BASE_URL`. The catalog of ~1,116
endpoints ships inside the package at
`canvas_api_mcp/data/catalog.json`. To match your deployment's exact feature
set, regenerate it:

```bash
python scripts/build_catalog.py https://canvas.yourschool.edu -o data/catalog.json
```

## Compliance

- **Academic integrity.** `submit_assignment` can submit anything, including
  AI-generated work. Submitting work that is not your own breaches the academic
  integrity rules of essentially every institution, and Canvas's API Policy
  explicitly prohibits use that violates them. That is on you.
- **Rate limiting.** The client throttles against Canvas's published quota. Do not
  remove it — overloading the API is prohibited.
- **Course material.** `read_file` fetches materials for your own study. Do not
  redistribute them.
- **Your token is password-equivalent.** It can read your grades and submit work as
  you. Set an expiry. Never commit it.
- **Personal-use scope.** Phase 1 targets a single student using their own token.
  There are no curated educator tools; Canvas's OAuth flow has no PKCE, so this
  locally-installed server cannot implement the multi-user OAuth that Canvas's API
  Policy requires for anything broader. Do not repackage this as a multi-tenant
  service.

## Development

```bash
uv sync
uv run pytest -v

# Live tests against your real account (read-only)
CANVAS_LIVE_TESTS=1 uv run pytest tests/test_live.py -v
```

Environment variables: `CANVAS_BASE_URL`, `CANVAS_TOKEN`, optional
`CANVAS_MAX_PAGES` (default 10). See `env.template`.

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for
setup, the architectural rules worth knowing before you change anything, and the bar
for adding a new curated tool.

Found a security problem? **Do not open a public issue.** See
[SECURITY.md](SECURITY.md) for private reporting — particularly important here, since
this project handles password-equivalent Canvas tokens.

Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Licence

[MIT](LICENSE) © 2026 Johannsen Lum.

Use it, change it, redistribute it, build something commercial on it — the only
condition is that you keep the copyright notice and licence text. It comes with no
warranty of any kind.

Contributions are accepted under the same licence.
