# CodeBrain CLI

Connect your codebase to CodeBrain — a persistent understanding layer for your AI coding assistant.

## Install

```bash
pip install git+https://github.com/DawerJ/CodeBrain-CLI.git
```

## Quick start (new user)

```bash
codebrain signup   # create an account
codebrain demo     # build a real codebase and see CodeBrain in action
```

Or, to set up your own project:

```bash
codebrain new      # set up your project
```

Then open your project in Claude Code and run `/project:session-start`.

## Quick start (returning user, new project)

```bash
codebrain login
codebrain new
```

## Joining a teammate's project

```bash
codebrain login
codebrain join     # fills in .mcp.json from the committed .mcp.json.template
```

## What `codebrain new` sets up

- `.codebrain` — local config (gitignored, contains your API key)
- `.mcp.json` — MCP server config for Claude Code (gitignored)
- `.mcp.json.template` — template for teammates to fill in (commit this)
- `CLAUDE.md` — project instructions for Claude Code (commit this)
- `.claude/commands/` — `/project:session-start` and `/project:session-end` slash commands

## Other commands

```bash
codebrain demo       # build a real codebase from scratch and see CodeBrain in action
codebrain up         # verify connection, check for updates
codebrain upgrade    # refresh CLAUDE.md and slash commands to latest templates
codebrain rescan     # scan source files and push to CodeBrain
codebrain ci         # scaffold a GitHub Actions workflow for automatic rescanning
codebrain status     # show codebase status, staleness, active claims
```
