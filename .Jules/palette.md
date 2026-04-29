## 2026-04-29 - Accessibility of Icon-Only Navigation Buttons
**Learning:** Standard NiceGUI `ui.button(icon=...)` components used in global navigation structures (like the top bar) lack both visual hover context and screen-reader semantics by default, making them inaccessible to keyboard/assistive users and ambiguous to mouse users.
**Action:** Always append explicit `.props('aria-label="<Action Name>"')` for Quasar ARIA compliance and chain `.tooltip('<Action Name>')` for visual context whenever creating icon-only buttons in NiceGUI, particularly in navigation or toolbar areas.
