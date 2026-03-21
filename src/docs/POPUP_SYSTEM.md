# Zen IDE Popup System Documentation

## Overview

The Zen IDE popup system is built around the `NvimPopup` base class, which provides a consistent, modal popup experience across the application. This document explains how the popup system works, its automatic closing mechanisms, and how to properly implement custom popups.

## Architecture

### Base Classes

#### `NvimPopup` (popups/nvim_popup.py)
The base class for all popups in Zen IDE. Provides:
- Automatic focus management
- Multiple auto-closing mechanisms for modal behavior
- Keyboard handling (Escape key)
- Consistent styling and behavior

#### `NvimContextMenu` vs `SystemContextMenu`
- **NvimContextMenu**: Custom popup-based context menu that integrates with the popup system
- **SystemContextMenu**: GTK-native popover-based context menu for system integration

## Popup Closing Mechanisms

The `NvimPopup` base class implements **three different mechanisms** to automatically close popups when they lose focus. This ensures modal behavior where popups close when the user clicks outside or switches focus.

### 1. Focus-Based Closing (`_on_focus_leave`)

**Mechanism**: Uses GTK's focus controller to detect when focus leaves the popup window.

```python
def _on_focus_leave(self):
    """Close popup when focus leaves (unless closing or has sub-popup)."""
    if self._closing or self._sub_popup:
        return
    self.close()
```

**When triggered**: 
- User clicks outside the popup
- User Alt+Tab to another window
- Another widget grabs focus

### 2. Active State Closing (`_on_active_changed`) - Linux Fallback

**Mechanism**: Uses GTK's `is-active` property to detect when the window loses active state.

```python
def _on_active_changed(self, window, active):
    """Handle window active state changes (Linux fallback)."""
    if not active and not self._closing:
        self._check_active_and_close()
```

**When triggered**:
- Window manager deactivates the window
- User switches to another application
- Backup mechanism when focus events don't work properly

### 3. Delayed Active Check (`_check_active_and_close`)

**Mechanism**: Timer-based check that verifies if the popup should still be open.

```python
def _check_active_and_close(self):
    """Check if popup should close based on active state."""
    if self._closing or self._sub_popup:
        return
    
    if not self.is_active():
        GLib.timeout_add(100, self._delayed_active_check)
```

**When triggered**:
- Delayed after active state changes
- Backup mechanism for edge cases
- Handles timing-sensitive scenarios

### Why Three Mechanisms?

Different desktop environments and GTK versions handle focus and window activation differently. Having three overlapping mechanisms ensures reliable popup closing across:
- Different Linux distributions
- Various window managers (GNOME, KDE, XFCE, etc.)
- Different GTK versions
- X11 vs Wayland

## Sub-Popup Support

Popups can have "sub-popups" (like context menus or dropdowns). The `_sub_popup` mechanism prevents the main popup from closing when a sub-popup is active.

### Sub-Popup Workflow

1. **Opening Sub-Popup**:
   ```python
   def _on_button_clicked(self):
       context_menu = show_context_menu(...)
       self._sub_popup = context_menu
       context_menu.connect("close-request", self._on_sub_popup_closing)
   ```

2. **Sub-Popup Active**:
   - All auto-closing mechanisms check `if self._sub_popup:` and return early
   - Main popup remains open even if focus changes

3. **Sub-Popup Closing**:
   ```python
   def _on_sub_popup_closing(self):
       # Restore focus first, then clear sub-popup reference
       GLib.idle_add(self._restore_focus_and_clear_sub_popup)
   
   def _restore_focus_and_clear_sub_popup(self):
       self._some_widget.grab_focus()  # Restore focus to main popup
       self._sub_popup = None          # Clear reference
   ```

## The Font Picker Dialog Case Study

The font picker dialog (`FontPickerDialog`) demonstrates a special case where **all automatic closing mechanisms are disabled** because the popup should behave like a traditional modal dialog.

### Problem

The font picker has an "Apply to" combo box that opens a context menu. The original implementation had these issues:

1. **Wrong signal connection**: Connected to "close-request" for all context menus, but `SystemContextMenu` emits "closed"
2. **Premature clearing**: `_sub_popup` was cleared when item was selected, before menu closed
3. **Race condition**: Focus restoration happened after `_sub_popup` was cleared
4. **Multiple triggers**: Any of the three auto-close mechanisms could trigger during button interaction

### Solution

The font picker overrides **all three auto-closing mechanisms** to prevent unexpected closing:

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

This makes the font picker behave like a traditional modal dialog that only closes when:
- User clicks "Cancel"
- User clicks "Apply"  
- User presses Escape key

### Signal Handling Fix

The font picker now properly handles both context menu types:

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

## Best Practices

### When to Use Automatic Closing

**Use automatic closing** (default `NvimPopup` behavior) for:
- Search popups
- Quick selection dialogs
- Tool tips and info popups
- Context menus
- Temporary overlays

### When to Disable Automatic Closing

**Disable automatic closing** (override all three methods) for:
- Configuration dialogs
- Complex forms with multiple controls
- Dialogs with unsaved changes
- Multi-step wizards
- Any dialog where accidental closing would lose user work

### Implementing Sub-Popups

1. **Set `_sub_popup` immediately** when opening:
   ```python
   context_menu = show_context_menu(...)
   self._sub_popup = context_menu  # Set BEFORE any focus changes
   ```

2. **Connect to correct signal**:
   ```python
   if isinstance(context_menu, NvimPopup):
       context_menu.connect("close-request", self._on_sub_popup_closing)
   else:
       context_menu.connect("closed", self._on_sub_popup_closing)
   ```

3. **Don't clear `_sub_popup` prematurely**:
   ```python
   def _on_item_selected(self, item):
       # Update UI, but DON'T clear _sub_popup here
       self._update_selection(item)
       # _sub_popup will be cleared in _on_sub_popup_closing
   ```

4. **Restore focus before clearing**:
   ```python
   def _on_sub_popup_closing(self):
       GLib.idle_add(self._restore_focus_and_clear_sub_popup)
   
   def _restore_focus_and_clear_sub_popup(self):
       self._main_widget.grab_focus()
       self._sub_popup = None
   ```

### Custom Popup Implementation

```python
class MyCustomPopup(NvimPopup):
    def __init__(self, parent, data):
        super().__init__(parent, "My Custom Popup")
        self._setup_ui()
    
    def _setup_ui(self):
        # Create your UI elements
        pass
    
    # Option 1: Use default auto-closing behavior (most popups)
    # No overrides needed
    
    # Option 2: Disable auto-closing (modal dialogs)
    def _on_focus_leave(self):
        return
    
    def _on_active_changed(self, window, active):
        return
    
    def _check_active_and_close(self):
        return
    
    # Option 3: Custom auto-closing logic
    def _on_focus_leave(self):
        if self._has_unsaved_changes():
            return  # Don't close if there are unsaved changes
        super()._on_focus_leave()  # Use default behavior otherwise
```

## Testing

Comprehensive regression tests ensure the popup system works correctly:

### Test Coverage

1. **Auto-closing mechanism tests**:
   - Focus leave detection
   - Active state change handling
   - Delayed closing checks

2. **Sub-popup integration tests**:
   - Context menu opening/closing
   - Signal connection (NvimContextMenu vs SystemContextMenu)
   - Focus restoration

3. **Manual closing tests**:
   - Button clicks (OK, Cancel)
   - Keyboard shortcuts (Escape)

4. **Integration tests**:
   - Complete user workflows
   - Edge cases and timing issues

### Running Tests

```bash
# Run font popup specific tests
cd tests
python run_font_popup_tests.py

# Run all tests
python -m unittest discover -s . -p "test_*.py" -v
```

## Troubleshooting

### Common Issues

1. **Popup closes unexpectedly**:
   - Check if you need to disable auto-closing mechanisms
   - Verify `_sub_popup` is set before any focus changes
   - Ensure correct signal connections

2. **Sub-popup doesn't work**:
   - Check signal connection (close-request vs closed)
   - Verify `_sub_popup` is not cleared prematurely
   - Ensure focus restoration happens before clearing

3. **Popup doesn't close when expected**:
   - Verify auto-closing methods aren't overridden incorrectly
   - Check that manual close methods call `self.close()`
   - Ensure keyboard handling is implemented

### Debug Output

Add debug output to trace popup behavior:

```python
def _on_focus_leave(self):
    print(f"Focus leave: closing={self._closing}, sub_popup={self._sub_popup}")
    if self._closing or self._sub_popup:
        return
    print("Closing popup due to focus leave")
    self.close()
```

## Summary

The Zen IDE popup system provides robust, consistent modal behavior through:

- **Three overlapping auto-closing mechanisms** for reliability across environments
- **Sub-popup support** for complex UI interactions
- **Flexible override system** for custom behavior
- **Comprehensive testing** to prevent regressions

Understanding these mechanisms allows you to create popups that behave correctly in all scenarios while providing a consistent user experience.