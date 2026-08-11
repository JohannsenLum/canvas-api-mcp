# Example configurations

Ready-to-copy config for each MCP client. Replace `CANVAS_BASE_URL` with your own
institution and paste your token in place of `your-token-here`.

Full walkthrough including token creation:
<https://mcp.johannsenlum.com/canvas-lms/install>

| File | Client | macOS | Windows | Linux |
|---|---|---|---|---|
| [`claude-code.json`](claude-code.json) | Claude Code | `~/.claude.json` | `%USERPROFILE%\.claude.json` | `~/.claude.json` |
| [`claude-desktop.json`](claude-desktop.json) | Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` | `%APPDATA%\Claude\claude_desktop_config.json` | no official Linux build |
| [`cursor.json`](cursor.json) | Cursor | `~/.cursor/mcp.json` | `%USERPROFILE%\.cursor\mcp.json` | `~/.cursor/mcp.json` |
| [`vscode.json`](vscode.json) | VS Code / Copilot | `.vscode/mcp.json` (workspace-relative, same on every platform) | ⟵ | ⟵ |
| [`zed.json`](zed.json) | Zed | `~/Library/Application Support/Zed/settings.json` | `%APPDATA%\Zed\settings.json` | `~/.config/zed/settings.json` |

Rather than guess, prefer each client's own "open config" command. Claude Desktop has
**Settings → Developer → Edit Config**, and Cursor and Zed both open their settings file
from the command palette. That always beats a path table, which goes stale when a client
moves its config.

Claude Desktop is macOS and Windows only; there is no official Linux build, so no Linux
path is listed. Zed's Linux path is from
[Zed's configuration docs](https://zed.dev/docs/configuring-zed); the rest are from each
client's own documentation.

Note the top-level key differs between clients: VS Code uses `servers`, Zed uses
`context_servers`, everyone else uses `mcpServers`. Copying the wrong one is the most
common setup failure.

## Command line instead

Claude Code can do it in one command, no file editing:

```bash
claude mcp add canvas -s user \
  -e CANVAS_BASE_URL=https://canvas.nus.edu.sg \
  -e CANVAS_TOKEN=your-token-here \
  -- uvx canvas-api-mcp
```

Everything after `--` is the command Claude Code will spawn.

## Install from source (contributors / unreleased `main`)

Not part of the normal install path above, only needed if you want the latest
unreleased code instead of the published PyPI release:

```bash
uvx --from git+https://github.com/JohannsenLum/canvas-api-mcp canvas-api-mcp
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
