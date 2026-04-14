# AI Chat

Zen IDE includes a multi-session AI chat panel for interactive conversations with Claude Code, Gemini CLI, or GitHub Copilot.

## Opening AI Chat

The AI chat panel lives on the right side of the IDE. Click the AI chat tab to open it. Multiple chat sessions run in parallel.

## Chat Interface

```
┌────────────────────────────────────┐
│ [Chat 1] [Chat 2] [+ New]         │  ← session tabs
├────────────────────────────────────┤
│                                    │
│  AI: Here's how to refactor...     │  ← scrollable chat
│  You: Can you also add tests?      │
│  AI: Sure! Here's the test...      │
│                                    │
│ ┌────────────────────────────────┐ │
│ │ Type your message...           │ │  ← input field
│ └────────────────────────────────┘ │
└────────────────────────────────────┘
```

## Features

### Multiple Chat Sessions
- Click **+** to start a new conversation
- Each session is independent with its own context and history
- Tab titles are auto-generated from the first message
- Rename tabs by right-clicking

### Streaming Responses
- AI responses stream in real-time, token by token
- Markdown is rendered inline (code blocks, bold, lists)
- ANSI colours are preserved

### Tool Use
- When `ai.yolo_mode` is `true` (default), the AI can directly execute actions like writing files or running terminal commands without asking for confirmation
- When `false`, you'll be prompted to approve each tool action

### Context Awareness
The AI automatically has context about:
- The currently open file and cursor position
- The workspace structure
- Recent terminal output

### Auto-Scroll
Chat automatically scrolls to show new output while the AI is responding. If you scroll up to read earlier messages, auto-scroll pauses until the response finishes.

Toggle: `ai.auto_scroll_on_output` (default: `true`)

### Chat History
- Press `Cmd+H` to view AI chat history
- Sessions persist across IDE restarts

## Layout Modes

### Vertical Stack (default: `false`)

```json
{ "behavior.ai_chat_on_vertical_stack": true }
```

Multiple chat panes stacked vertically (like terminals).

### Tab Mode (default)

```json
{ "behavior.ai_chat_on_vertical_stack": false }
```

Chat sessions as horizontal tabs — only one visible at a time.

## Tips

- **Ask about your code** — The AI sees your open file, so you can ask "refactor this function" or "add error handling here"
- **Multiple sessions** — Use one chat for questions about your project and another for general coding questions
- **Long conversations** — Start a new session if the conversation gets too long; context windows have limits
