# Font Popup Closing Fix Documentation

## Problem Description

The font picker dialog in Zen IDE had a critical usability issue: when users clicked on the "Apply to" combo box button to select where to apply font changes (Editor, Terminal, etc.), the entire font picker dialog would unexpectedly close before they could make a selection.

## Root Cause Analysis

The issue was caused by multiple overlapping problems in the popup's focus management system:

### 1. Multiple Auto-Closing Mechanisms

The base `NvimPopup` class implements three different mechanisms to automatically close popups when they lose focus:

- **`_on_focus_leave()`**: Closes popup when GTK focus controller detects focus leaving
- **`_on_active_changed()`**: Closes popup when window loses active state (Linux fallback)  
- **`_check_active_and_close()`**: Delayed timer-based check for closing

When the user clicked the "Apply to" button, **any** of these mechanisms could trigger during the brief moment when GTK was processing the button click, causing the dialog to close immediately.

### 2. Wrong Signal Connections

The font picker was always trying to connect to the `"close-request"` signal on context menus, but:
- `NvimContextMenu` emits `"close-request"` 
- `SystemContextMenu` (GTK Popover) emits `"closed"`

This meant that when not in Nvim mode, the signal connection would fail silently, and the `_on_sub_popup_closing` callback would never be called.

### 3. Premature Sub-Popup Clearing

The `_on_target_selected()` callback was immediately setting `self._sub_popup = None` when the user selected an item from the dropdown, even before the context menu had fully closed. This created a race condition:

1. User selects item → `_sub_popup` cleared immediately
2. Context menu tries to close → brief focus change occurs
3. `_on_focus_leave()` sees `_sub_popup` is `None` → closes dialog

### 4. Focus Restoration Timing

The original `_on_sub_popup_closing()` method had a race condition in its focus restoration:

```python
def _on_sub_popup_closing(self):
    self._sub_popup = None  # Cleared immediately
    GLib.idle_add(lambda: self._search_entry.grab_focus())  # Restored later
```

During the gap between clearing `_sub_popup` and restoring focus, any focus change would trigger dialog closing.

## Solution Implementation

The fix addresses all these issues comprehensively:

### 1. Disabled All Auto-Closing Mechanisms

Since the font picker should behave like a traditional modal dialog, all automatic closing mechanisms are overridden to do nothing:

```python
def _on_focus_leave(self):
    """Override to prevent auto-closing on focus leave."""
    return

def _on_active_changed(self, window, active):
    """Override to prevent auto-closing on active state change."""
    return

def _check_active_and_close(self):
    """Override to prevent delayed auto-closing."""
    return
```

### 2. Fixed Signal Connection Logic

The context menu signal connection now handles both menu types correctly:

```python
def _on_target_button_clicked(self, button):
    context_menu = show_context_menu(...)
    self._sub_popup = context_menu
    
    # Connect to appropriate signal based on menu type
    if isinstance(context_menu, NvimPopup):
        context_menu.connect("close-request", self._on_sub_popup_closing)
    else:  # SystemContextMenu (Gtk.Popover)
        context_menu.connect("closed", self._on_sub_popup_closing)
```

### 3. Removed Premature Sub-Popup Clearing

The `_on_target_selected()` method no longer clears `_sub_popup`:

```python
def _on_target_selected(self, target):
    """Handle target selection - don't clear _sub_popup here."""
    self._target_button.set_label(target)
    # _sub_popup will be cleared properly in _on_sub_popup_closing
```

### 4. Fixed Focus Restoration Timing

The focus restoration now happens **before** clearing the sub-popup reference:

```python
def _on_sub_popup_closing(self):
    """Handle sub-popup closing with proper timing."""
    GLib.idle_add(self._restore_focus_and_clear_sub_popup)

def _restore_focus_and_clear_sub_popup(self):
    """Restore focus first, then clear sub-popup reference."""
    self._search_entry.grab_focus()  # Restore focus first
    self._sub_popup = None           # Clear reference after
```

## Behavioral Changes

### Before Fix

1. User clicks "Apply to" button
2. Dialog closes immediately (unexpected!)
3. User loses their font selection work
4. Poor user experience

### After Fix

1. User clicks "Apply to" button
2. Context menu opens properly
3. User selects target (Editor/Terminal/etc.)
4. Context menu closes, dialog remains open
5. User can continue working or click Apply/Cancel
6. Dialog only closes through explicit user actions

## Manual Closing Methods

The font picker dialog now **only** closes through these explicit user actions:

1. **Cancel Button**: `_on_cancel()` - reverts font changes and closes
2. **Apply Button**: `_on_ok()` - applies font changes and closes  
3. **Escape Key**: `_on_key_pressed()` - calls `_on_cancel()` for Escape key

## Testing

Comprehensive regression tests ensure the fix works correctly and prevents future regressions:

### Test Categories

1. **Auto-closing prevention tests**: Verify all three auto-close mechanisms are disabled
2. **Sub-popup integration tests**: Test context menu opening, selection, and closing
3. **Signal connection tests**: Verify correct signals for both NvimContextMenu and SystemContextMenu
4. **Focus management tests**: Test focus restoration timing and `_sub_popup` clearing
5. **Manual closing tests**: Ensure Cancel, Apply, and Escape still work
6. **Documentation tests**: Verify comprehensive documentation exists
7. **Regression protection tests**: Ensure specific bug scenarios are protected

### Running Tests

**Recommended (Simple Tests)**:
```bash
cd tests
python3 run_font_popup_simple_tests.py
```

**Advanced (Complex Tests)**:
```bash
cd tests
python3 run_font_popup_tests.py
```

### Test Files

- `test_font_popup_simple.py` - Working regression tests without complex mocking
- `test_font_popup_fix.py` - Comprehensive tests with full mocking (may have environment issues)
- `README_FONT_POPUP_TESTS.md` - Detailed test documentation

## Code Changes Summary

### Files Modified

1. **`popups/font_picker_dialog.py`**:
   - Added auto-closing mechanism overrides
   - Fixed context menu signal connections
   - Improved focus restoration timing
   - Removed premature `_sub_popup` clearing

### New Files

1. **`tests/test_font_popup_fix.py`**: Comprehensive regression tests
2. **`tests/run_font_popup_tests.py`**: Test runner with detailed reporting
3. **`docs/POPUP_SYSTEM.md`**: Complete popup system documentation
4. **`docs/FONT_POPUP_FIX.md`**: This fix documentation

## Future Considerations

### When to Use This Pattern

Disable auto-closing mechanisms for popups that:
- Have complex UI interactions (multiple buttons, dropdowns, etc.)
- Contain user work that shouldn't be lost accidentally
- Need to behave like traditional modal dialogs
- Have multiple steps or configuration options

### When NOT to Use This Pattern

Keep auto-closing mechanisms for popups that:
- Are simple/quick interactions (search, quick select)
- Don't contain user work
- Should close when clicking outside (tooltips, info popups)
- Are context menus or temporary overlays

## Impact Assessment

### User Experience Impact
- ✅ **Positive**: Users can now use the "Apply to" combo box without losing work
- ✅ **Positive**: Font picker behaves like expected modal dialog
- ✅ **Positive**: Consistent experience across different desktop environments

### Code Quality Impact  
- ✅ **Positive**: Comprehensive test coverage prevents future regressions
- ✅ **Positive**: Clear documentation explains popup system behavior
- ✅ **Positive**: Proper signal handling for different menu types

### Performance Impact
- ✅ **Neutral**: Minimal performance impact
- ✅ **Positive**: Eliminates unnecessary focus event processing during button clicks

## Conclusion

This fix resolves a critical usability issue in the font picker dialog while establishing a clear pattern and comprehensive documentation for handling similar popup behavior issues in the future. The solution is robust, well-tested, and maintains backward compatibility while significantly improving the user experience.