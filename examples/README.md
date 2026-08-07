# Example configurations

Ready-to-copy config for each MCP client. Replace `CANVAS_BASE_URL` with your own
institution and paste your token in place of `your-token-here`.

Full walkthrough including token creation:
<https://mcp.johannsenlum.com/canvas-lms/install>

| File | Client | Config location |
|---|---|---|
| [`claude-code.json`](claude-code.json) | Claude Code | `~/.claude.json` |
| [`claude-desktop.json`](claude-desktop.json) | Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| [`cursor.json`](cursor.json) | Cursor | `~/.cursor/mcp.json` |
| [`vscode.json`](vscode.json) | VS Code / Copilot | `.vscode/mcp.json` |
| [`zed.json`](zed.json) | Zed | `settings.json` |

Note the top-level key differs between clients — VS Code uses `servers`, Zed uses
`context_servers`, everyone else uses `mcpServers`. Copying the wrong one is the most
common setup failure.

## Command line instead

Claude Code can do it in one command, no file editing:

```bash
claude mcp add canvas -s user \
  -e CANVAS_BASE_URL=https://canvas.nus.edu.sg \
  -e CANVAS_TOKEN=your-token-here \
  -- uvx --from git+https://github.com/JohannsenLum/canvas-api-mcp canvas-api-mcp
```

Everything after `--` is the command Claude Code will spawn. The separator matters —
without it, `--from` gets parsed as a flag to `claude mcp add` itself.

## Once published to PyPI

Every example uses `uvx --from git+https://github.com/JohannsenLum/canvas-api-mcp`,
which works today. Once the package is on PyPI this shortens to:

```jsonc
"args": ["canvas-api-mcp"]
```

## Things to ask it

```
what's due in the next two weeks?
how am I doing in CS3230?
what do I need on the final to keep a B+?
summarise the week 7 lecture slides for CS2040S
have I submitted problem set 3?
what did the prof say in the last announcement?
list my group memberships          ← goes via the gateway, no curated tool
```
