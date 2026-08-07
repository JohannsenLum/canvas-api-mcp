<!-- mcp-name: io.github.JohannsenLum/canvas-api-mcp -->

# canvas-api-mcp

An MCP server for Canvas LMS. 15 curated tools for everyday student work, plus a
gateway that reaches every endpoint your Canvas instance exposes.

> **Personal-use software.** Canvas's API Policy requires OAuth for applications used
> by multiple people, and Canvas OAuth cannot be implemented safely by locally
> installed software (no PKCE, and `client_secret` cannot be shipped in a package).
> Use this with your own token on your own account. See [Compliance](#compliance).

## Requirements

- Python 3.11+
- A Canvas personal access token. Your institution must allow students to create them:
  check **Canvas → Account → Settings → Approved Integrations** for a
  **"+ New access token"** button.

## Install

```bash
uvx canvas-api-mcp   # no install step; downloads and runs
```

Or from source:

```bash
git clone https://github.com/<you>/canvas-api-mcp
cd canvas-api-mcp
uv sync
```

## Configure

Add to your MCP client's config. **Claude Code** (`~/.claude.json`):

```jsonc
{
  "mcpServers": {
    "canvas": {
      "command": "uvx",
      "args": ["canvas-api-mcp"],
      "env": {
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
        "CANVAS_TOKEN": "your-token-here"
      }
    }
  }
}
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS) and **Cursor** (`~/.cursor/mcp.json`) take the same `mcpServers` block.

Your token stays on your machine, in your own config file. It is never transmitted
anywhere except directly to your Canvas instance.

## Tools

| Tool | What it does |
|---|---|
| `whoami` | Identity and your role in each course |
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
| `search_canvas_api` | Find any endpoint by keyword |
| `canvas_request` ✏️ | Execute any endpoint |

✏️ writes to Canvas.

`search_canvas_api` + `canvas_request` reach all ~1,100 endpoints your instance
exposes. What they may do is decided by Canvas from your token's permissions — a
teacher token unlocks educator endpoints with no change to this server.

## Prompts

`week_ahead`, `study_pack`, `grade_check`.

## Other institutions

Works with any Canvas instance — set `CANVAS_BASE_URL`. To match your deployment's
exact feature set, regenerate the endpoint catalog:

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

## Development

```bash
uv sync
uv run pytest -v

# Live tests against your real account (read-only)
CANVAS_LIVE_TESTS=1 uv run pytest tests/test_live.py -v
```

## Licence

MIT
