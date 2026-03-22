from ai.ai_chat_tabs import AIChatTabs

from ai import ai_chat_tabs as ai_chat_tabs_module


class TestSwitchToSession:
    class _FakeTabButton:
        def __init__(self):
            self.selected_states = []

        def set_selected(self, selected):
            self.selected_states.append(selected)

    class _FakeStack:
        def __init__(self):
            self.visible_children = []

        def set_visible_child_name(self, name):
            self.visible_children.append(name)

    class _FakeChat:
        def __init__(self, pending_restore=False):
            self._pending_restore = pending_restore
            self.ensure_restored_calls = 0
            self.ensure_restored_modes = []
            self.scroll_calls = 0
            self.focus_calls = 0

        def ensure_restored(self, scroll_mode="none"):
            self.ensure_restored_calls += 1
            self.ensure_restored_modes.append(scroll_mode)
            return False

        def scroll_to_bottom(self):
            self.scroll_calls += 1
            return False

        def focus_input(self):
            self.focus_calls += 1

    def test_same_session_does_not_force_scroll_or_focus(self, monkeypatch):
        current_chat = self._FakeChat()
        tabs = AIChatTabs.__new__(AIChatTabs)
        tabs._vertical_mode = False
        tabs.active_session_idx = 0
        tabs.content_stack = self._FakeStack()
        tabs._update_header_from_chat = lambda chat: None
        tabs._save_sessions_state = lambda: None
        tabs.sessions = [
            {
                "chat": current_chat,
                "tab_btn": self._FakeTabButton(),
                "session_id": 1,
                "stack_name": "chat_1",
            }
        ]

        monkeypatch.setattr(ai_chat_tabs_module.GLib, "idle_add", lambda callback, *args: callback(*args))

        tabs.switch_to_session(0)

        assert current_chat.ensure_restored_calls == 1
        assert current_chat.ensure_restored_modes == ["none"]
        assert current_chat.scroll_calls == 0
        assert current_chat.focus_calls == 0

    def test_switching_tabs_scrolls_to_bottom_once_visible(self, monkeypatch):
        old_chat = self._FakeChat()
        new_chat = self._FakeChat()
        old_tab = self._FakeTabButton()
        new_tab = self._FakeTabButton()
        tabs = AIChatTabs.__new__(AIChatTabs)
        tabs._vertical_mode = False
        tabs.active_session_idx = 0
        tabs.content_stack = self._FakeStack()
        tabs._update_header_from_chat = lambda chat: None
        tabs._save_sessions_state = lambda: None
        tabs.sessions = [
            {
                "chat": old_chat,
                "tab_btn": old_tab,
                "session_id": 1,
                "stack_name": "chat_1",
            },
            {
                "chat": new_chat,
                "tab_btn": new_tab,
                "session_id": 2,
                "stack_name": "chat_2",
            },
        ]

        monkeypatch.setattr(ai_chat_tabs_module.GLib, "idle_add", lambda callback, *args: callback(*args))

        tabs.switch_to_session(1)

        assert old_tab.selected_states == [False]
        assert new_tab.selected_states == [True]
        assert tabs.content_stack.visible_children == ["chat_2"]
        assert new_chat.ensure_restored_calls == 1
        assert new_chat.ensure_restored_modes == ["bottom"]
        assert new_chat.scroll_calls == 1
        assert new_chat.focus_calls == 1
