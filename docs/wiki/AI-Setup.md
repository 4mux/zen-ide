# AI Setup & Providers

Zen IDE has two AI subsystems:

- **AI chat** runs the `claude` or `copilot` CLI directly inside the integrated AI Terminal.
- **Inline completions** still use Copilot-backed ghost text suggestions in the editor.

AI chat is **not API-based anymore**. Zen no longer asks you for Anthropic or OpenAI API keys for chat.

## Supported Providers

| Feature | Backend | Auth | Notes |
|---|---|---|---|
| **AI chat** | `claude` CLI | Claude CLI login | Preferred when available |
| **AI chat** | `copilot` CLI | GitHub Copilot CLI login | Used when selected or when Claude is unavailable |
| **Inline completions** | Copilot HTTP auth | GitHub Copilot subscription/login | Separate from chat |

## Setup

### AI Chat (CLI-based)

Install one or both CLI tools, then authenticate with each tool's own login flow:

- **Claude CLI** — install `claude`, then run `claude login`
- **GitHub Copilot CLI** — install `copilot`, then run `copilot auth`

Zen auto-detects installed CLIs and starts the AI Terminal with the best available option:

1. `claude`
2. `copilot`

If neither CLI is installed, AI chat cannot start until one is available on your `PATH`.

### Inline Completions

Inline ghost text suggestions are still powered by Copilot auth on your machine.

Token resolution order:

1. `~/.config/github-copilot/apps.json`
2. `~/.zen_ide/api_keys.json`
3. `GITHUB_TOKEN`

## Provider Auto-Detection

On startup, Zen IDE checks providers in this order:
1. **Claude CLI** — looks for `claude`
2. **Copilot CLI** — looks for `copilot`

The first available CLI is activated automatically for AI chat.

## Switching Providers

Use the provider dropdown in the AI chat header, or set `ai.provider` in `~/.zen_ide/settings.json`:

```json
{
  "ai.provider": "copilot_cli"
}
```

Valid values: `"claude_cli"`, `"copilot_cli"`, `""` (auto-detect)

You can also override the chat model:

```json
{
  "ai.model": "sonnet"
}
```

## AI Settings

| Setting | Default | Description |
|---|---|---|
| `ai.is_enabled` | `true` | Master toggle for all AI features |
| `ai.provider` | `""` | Active chat provider (`"claude_cli"`, `"copilot_cli"`, or `""` for auto-detect) |
| `ai.model` | `""` | Optional chat model override; empty uses the CLI default |
| `ai.show_inline_suggestions` | `true` | Show ghost text inline completions |
| `ai.yolo_mode` | `true` | Skip tool-use confirmation prompts |
| `ai.inline_completion.trigger_delay_ms` | `500` | Debounce delay before requesting completions |
| `ai.inline_completion.model` | `"gpt-4.1-mini"` | Model used for inline completions |

## Disabling AI

To completely disable AI features:

```json
{
  "ai.is_enabled": false
}
```

To disable only inline suggestions (keep chat):

```json
{
  "ai.show_inline_suggestions": false
}
```

## Troubleshooting

**"AI chat not starting"**
- Check that `claude` or `copilot` is installed and available on your `PATH`
- Run `claude --version` or `copilot --version` in a terminal to verify
- Check `ai.is_enabled` is `true`

**"Inline suggestions not working"**
- Check `ai.show_inline_suggestions` is `true`
- Verify you have an active GitHub Copilot subscription
- If needed, re-authenticate Copilot in another editor so `~/.config/github-copilot/apps.json` is refreshed

For the full architecture and current behavior, see [`../2026_03_21_ai_terminal.md`](../2026_03_21_ai_terminal.md).
