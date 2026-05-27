# CodeBrain Client

Connect your project to a CodeBrain server.

## Install (teammates)

Since the CodeBrain repo is private, install from the cloned repo:

```bash
git clone https://github.com/DawerJ/codebrain.git
cd codebrain
pip install .
```

This installs the `codebrain` CLI and all dependencies.

## Quick start

```bash
# First time in a new project
codebrain init \
  --name "MyProject" \
  --url https://yourapp.railway.app \
  --api-key cb_... \
  --path ./src \
  --scan

# Every morning / session start
codebrain up
```

`codebrain init` generates:
- `.codebrain` — local config (gitignored, has your API key)
- `.mcp.json` — MCP server config for Claude Code (gitignored, has abs paths)
- `.mcp.json.template` — template for teammates to fill in (commit this)
- `CLAUDE.md` — project instructions for Claude Code (commit this)
- `.claude/commands/` — `/project:session-start` and `/project:session-end` slash commands

`codebrain up` checks connectivity and prints your status.
`codebrain up --watch` also starts a file watcher.

## Getting your API key

1. Open the CodeBrain webapp
2. Go to Settings → API Key
3. Copy your key

## Teammate setup (for existing projects)

```bash
git clone https://github.com/DawerJ/codebrain.git
pip install -e /path/to/codebrain   # install the main package
cd your-project
cp .mcp.json.template .mcp.json
# Edit .mcp.json: fill in your Python path and API key
codebrain up
```
