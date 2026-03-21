# AI SETUP GUIDE

**Created_at:** 2026-01-25
**Updated_at:** 2026-03-21
**Status:** Superseded
**Goal:** Document AI provider setup
**Scope:** AI chat, inline completions

> **Superseded:** The HTTP API providers (Anthropic, Copilot Chat, OpenAI) described below have been replaced by the VTE-based AI Terminal, which runs the `claude` or `copilot` CLI directly. See [2026_03_21_ai_terminal.md](2026_03_21_ai_terminal.md) for the current system. API keys are no longer managed by Zen IDE for chat — authentication is handled by the CLI tools themselves.

---

## Current Setup (2026-03-21)

### AI Chat — CLI-based

Zen IDE runs `claude` or `copilot` CLI directly in a VTE terminal. No API keys or HTTP configuration needed in Zen.

**Prerequisites:**
- Install the [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli) (`claude`) and/or [GitHub Copilot CLI](https://docs.github.com/en/copilot/github-copilot-in-the-cli) (`copilot`)
- Authenticate via each CLI's own auth flow (e.g., `claude login`, `copilot auth`)

Zen auto-detects installed CLIs. Configure the preferred provider via `ai.provider` setting (`"claude_cli"` or `"copilot_cli"`) or use the header dropdown in the AI panel.

### Inline Completions — Copilot HTTP API

Ghost-text inline completions still use the Copilot HTTP API directly. This requires a GitHub Copilot subscription.

**Token resolution order:**
1. `~/.config/github-copilot/apps.json` — auto-detected from any editor with Copilot auth
2. `~/.zen_ide/api_keys.json` — `{"github": "ghp_..."}` or `{"github": "ghu_..."}`
3. `GITHUB_TOKEN` environment variable

### Troubleshooting

**"AI chat not starting"**
- Check that `claude` or `copilot` CLI is installed and in your PATH
- Run `claude --version` or `copilot --version` in a terminal to verify
- Check `ai.is_enabled` is `true` in settings

**"Inline suggestions not working"**
- Check `ai.show_inline_suggestions` is `true` in settings
- Verify Copilot subscription is active
- Check `~/.config/github-copilot/apps.json` exists (authenticate Copilot in any editor)

---

## Historical: HTTP API Setup (Pre-2026-03-21)

The sections below are kept for reference but describe the old system.

### Copilot API (Old)

Used `api.githubcopilot.com/chat/completions` via direct HTTP. Token from `~/.config/github-copilot/apps.json` exchanged for session token.

### Anthropic API (Old)

Used `api.anthropic.com/v1/messages` via direct HTTP. API key from `ANTHROPIC_API_KEY` env var or `~/.zen_ide/api_keys.json`.

### OpenAI API (Old)

Used OpenAI-compatible endpoints via direct HTTP. API key from `OPENAI_API_KEY` env var or `~/.zen_ide/api_keys.json`.
