# AI Chat Debug Checklist

**Created_at:** 2026-03-10  
**Updated_at:** 2026-03-16  
**Status:** Superseded — rendering pipeline replaced by VTE terminal, see [2026_03_21_ai_terminal.md](2026_03_21_ai_terminal.md)
**Goal:** Provide a step-by-step checklist for diagnosing why AI chat responses fail to render.
**Scope:** `src/ai/ai_chat_terminal.py`, `src/ai/system_tag_stripper.py`, `src/ai/terminal_markdown_renderer.py`, `src/ai/chat_canvas.py`  

---

## QUICK START - Add These Logs Immediately

### 1. Check if response data is arriving
Location: `src/ai/ai_chat_terminal.py` line 1246-1254

```python
def _poll_pty_data(self):
    # ADD AFTER line 1247
    data = os.read(self._pty_master_fd, 8192)
    if data:  # ADD THIS LOG
        logger.debug(f"PTY data received: {len(data)} bytes")
    self._response_buffer.append(data)
```

**Expected:** Logs showing data chunks arriving, like "PTY data received: 512 bytes"

### 2. Check if tag stripper is buffering
Location: `src/ai/ai_chat_terminal.py` line 1254-1257

```python
text = data.decode("utf-8", errors="replace")
text = self._tag_stripper.feed(text)
# ADD THIS LOG
if not text:
    logger.debug("Tag stripper buffered input (returned empty)")
```

**Expected:** Some entries like "Tag stripper buffered input"
**Problem:** Too many = tags are stuck in buffer

### 3. Check if markdown renderer has output
Location: `src/ai/ai_chat_terminal.py` line 1258-1259

```python
formatted = self._md_renderer.feed(text)
# ADD THIS LOG
logger.debug(f"Markdown output: {len(formatted) if formatted else 0} chars, has_terminal={hasattr(self, 'terminal')}")
if not formatted and text:
    logger.warning(f"Markdown returned empty for input: {repr(text[:100])}")
```

**Expected:** Logs showing "Markdown output: 123 chars, has_terminal=True"
**Problem:** Logs showing "Markdown output: 0 chars" = renderer issue

### 4. Check if canvas feed is being called
Location: `src/ai/ai_chat_terminal.py` line 1265

```python
self.terminal.feed(canvas_text)
# WRAP IN TRY/EXCEPT
try:
    self.terminal.feed(canvas_text)
    logger.debug(f"Canvas fed {len(canvas_text)} chars")
except Exception as e:
    logger.error(f"Canvas.feed() failed: {e}", exc_info=True)
    self._append_text(f"\n[ERROR: {e}]\n")
```

**Expected:** "Canvas fed 123 chars" logs
**Problem:** Exception logged = canvas issue

---

## COMPREHENSIVE TEST CHECKLIST

### Test 1: Message Sending
- [ ] Click send button
- [ ] Check in DevTools: Is _on_send() called?
- [ ] Check logs: "Captured user message"
- [ ] User message should appear in UI
- [ ] File should be created at `~/.zen_ide/ai_chats/session_<id>.json`

### Test 2: CLI Process Launch
- [ ] Check logs: "AI CLI spawned with pid XXXX"
- [ ] Check logs: "PTY data received: X bytes"
- [ ] If no logs: CLI process didn't start
  - [ ] Check claude/copilot CLI is installed
  - [ ] Check path with: `which claude` or `which copilot`

### Test 3: Data Streaming
- [ ] Check logs: "PTY data received" messages
- [ ] Check logs: "Tag stripper buffered" messages
- [ ] Check logs: "Markdown output: X chars"
- [ ] Pattern: Data → stripper → markdown → canvas
- [ ] If any step returns empty, that's the break point

### Test 4: Canvas Display
- [ ] Check logs: "Canvas fed X chars"
- [ ] Check: terminal widget is visible
- [ ] Check: canvas has focus manager registered
- [ ] If no "Canvas fed" logs: display call never reached

### Test 5: Session File
- [ ] After message: File should exist with content
- [ ] After AI response: File should have assistant message
- [ ] Format check: 
```json
{
    "messages": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
    ]
}
```

### Test 6: Session Restore
- [ ] Close IDE
- [ ] Reopen IDE
- [ ] Chat session should restore
- [ ] Check logs: "Loaded X messages from..."
- [ ] Check logs: "Restored X messages to display"
- [ ] Previous messages should be visible

---

## SPECIFIC BUG SCENARIOS TO TEST

### Scenario A: Response Not Appearing (No Process)
```
User: "Hello"
[Spinner shows for 300s then "Timed out"]
No response appears
```

**Debug Steps:**
1. Check: Is claude/copilot CLI found?
   - Add log to line 1100: `logger.debug(f"Claude CLI path: {cli_path}")`
   - Add log to line 1118: `logger.debug(f"Copilot CLI path: {cli_path}")`

2. Check: Is subprocess starting?
   - Check logs for: "AI CLI spawned with pid"
   - If not: subprocess.Popen() failing silently

3. Check: Is PTY working?
   - Check logs for: "PTY data received"
   - If not: subprocess running but not producing output

### Scenario B: Response Not Appearing (Spinner Stops Early)
```
User: "Hello"
[Spinner stops immediately]
[No response visible]
```

**Debug Steps:**
1. Check: Is data arriving?
   - Look for: "PTY data received"
   - If yes: Data is arriving
   - If no: CLI not outputting

2. Check: Is tag stripper buffering?
   - Look for: "Tag stripper buffered input"
   - If many: Tags stuck in buffer
   - If few: Not the issue

3. Check: Is markdown returning empty?
   - Look for: "Markdown output: 0 chars"
   - If yes: Markdown issue
   - If no: Something else

4. Check: Is canvas.feed() called?
   - Look for: "Canvas fed X chars"
   - If no: Display never happens
   - If yes: Canvas rendering issue

### Scenario C: Response Appears But Is Wrong
```
User: "What's 2+2?"
AI: [Shows code/formatting/escape codes]
```

**Debug Steps:**
1. Check: Is ANSI stripping working?
   - Look at canvas content for escape codes: \033[...
   - If present: ANSI not stripped
   - Check: _on_cli_finished() line 1437-1438

2. Check: Is markdown rendering correct?
   - Add log to terminal_markdown_renderer.py
   - Verify color codes are being applied
   - Verify code blocks are formatted

### Scenario D: Session Not Saving
```
User types message
Chat responds
IDE closes
Reopen IDE
Chat is gone
```

**Debug Steps:**
1. Check: chat_messages_file path is set
   - Add log to _save_chat_messages() line 1640-1641
   - Verify path exists and is writable

2. Check: File is actually being written
   - Look at ~/.zen_ide/ai_chats/
   - Check file modification time
   - Add log: `logger.debug(f"Saving to {self.chat_messages_file}")`

3. Check: JSON is valid
   - Open file with text editor
   - Verify format: {"messages": [...]}

---

## KEY LOG LOCATIONS TO ADD

### File: `src/ai/ai_chat_terminal.py`

Line 1009 (_on_send):
```python
logger.debug(f"Send button clicked, message: {repr(message[:50])}")
```

Line 1027 (_on_send):
```python
logger.debug(f"Saved user message to file")
```

Line 1100-1103 (_run_ai_cli):
```python
logger.debug(f"Using Claude CLI at: {cli_path}")
```

Line 1146-1150 (_run_ai_cli):
```python
logger.debug(f"Processing started, is_processing={self._is_processing}")
```

Line 1167-1230 (_do_launch_cli):
```python
logger.info(f"CLI spawned with pid {self._vte_pid}, master_fd={self._pty_master_fd}")
```

Line 1247-1255 (_poll_pty_data):
```python
logger.debug(f"PTY read {len(data)} bytes")
text = self._tag_stripper.feed(text)
logger.debug(f"After stripper: {len(text) if text else 0} chars")
```

Line 1258-1259 (_poll_pty_data):
```python
formatted = self._md_renderer.feed(text)
logger.debug(f"Markdown: {len(formatted) if formatted else 0} chars, terminal={hasattr(self, 'terminal')}")
```

Line 1265 (_poll_pty_data):
```python
logger.debug(f"Feeding canvas {len(canvas_text)} chars")
self.terminal.feed(canvas_text)
logger.debug(f"Canvas feed successful")
```

Line 1392 (_on_cli_finished):
```python
logger.info(f"CLI finished, buffer has {len(self._response_buffer)} chunks, total {len(raw)} bytes")
```

Line 1442-1450 (_on_cli_finished):
```python
logger.info(f"Appending assistant response: {len(text)} chars")
self._save_chat_messages()
logger.debug(f"Saved {len(self.messages)} messages to file")
```

Line 1640 (_save_chat_messages):
```python
logger.debug(f"Saving {len(self.messages)} messages to {self.chat_messages_file}")
```

---

## FILES TO INSPECT

### Primary
- `src/ai/ai_chat_terminal.py` - Main display logic
- `src/ai/chat_canvas.py` - Canvas rendering
- `src/ai/terminal_markdown_renderer.py` - Markdown rendering
- `src/ai/system_tag_stripper.py` - Tag stripping

### Secondary
- `src/ai/ansi_buffer.py` - Text buffer implementation
- `src/ai/claude_cli_provider.py` - CLI interface

---

## ENVIRONMENT CHECKS

### Run These Commands

1. Check if Claude CLI exists:
```bash
which claude
# OR
~/.npm-global/bin/claude --version
```

2. Check if session directory exists:
```bash
ls -la ~/.zen_ide/ai_chats/
```

3. Check recent session file:
```bash
cat ~/.zen_ide/ai_chats/session_1.json | head -20
```

4. Check IDE logs:
```bash
tail -100 ~/.zen_ide/zen_ide.log
```

5. Run IDE with debug logging:
```bash
PYTHONUNBUFFERED=1 python src/zen_ide.py 2>&1 | grep -i "ai\|chat\|terminal"
```

---

## ROOT CAUSE DIAGNOSIS TREE

```
NO RESPONSE DISPLAYED
    |
    +-- Is spinner visible?
    |   |
    |   +-- NO: "Spinner never showed"
    |   |   +-- Check: _is_processing set?
    |   |   +-- Check: _start_spinner() called?
    |   |   +-- Check: Canvas visible?
    |   |
    |   +-- YES: "Spinner showed then stopped"
    |       +-- Check: Markdown returned empty?
    |       +-- Check: Canvas.feed() threw exception?
    |       +-- Check: Canvas render failed?
    |
    +-- Is data in response_buffer?
    |   |
    |   +-- NO: "Process output not captured"
    |   |   +-- Check: Is subprocess running?
    |   |   +-- Check: Is PTY opened correctly?
    |   |   +-- Check: CLI process exited early?
    |   |
    |   +-- YES: "Data captured but not displayed"
    |       +-- Check: Tag stripper output?
    |       +-- Check: Markdown output?
    |       +-- Check: Canvas.feed() called?
    |
    +-- Is message saved to file?
        |
        +-- NO: "Session file not saved"
        |   +-- Check: chat_messages_file path valid?
        |   +-- Check: File directory writable?
        |   +-- Check: _save_chat_messages() called?
        |
        +-- YES: "Message saved but not displayed"
            +-- This is display issue, not persistence issue
```

---

## PRIORITY FIXES

### HIGH PRIORITY
1. Add error handling to all terminal.feed() calls
2. Add logging to trace display path
3. Check if canvas widget is properly initialized

### MEDIUM PRIORITY  
4. Verify markdown renderer produces output
5. Check tag stripper doesn't buffer forever
6. Add canvas redraw verification

### LOW PRIORITY
7. Optimize polling frequency
8. Add metrics/telemetry
9. Improve error messages to user
