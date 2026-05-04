## 2026-04-23 - Accessibility for top nav buttons
**Learning:** The main top navigation bar used icon-only buttons (Menu, Filters, Inbox, Upload, Settings, Profile, Logout) which lacked proper accessibility labels. Using `.props('aria-label="..."')` and `.tooltip('...')` significantly improves navigation clarity for screen readers and visual users.
**Action:** Whenever creating icon-only buttons, always ensure an `aria-label` property and a `.tooltip()` are added by default.

## 2024-05-18 - Component Abstraction Props Iteration
**Learning:** When passing `aria-label` or `tooltip` strings as props into NiceGUI abstracted sub-components (like `_render_corner_toggle_button`), you must remember to explicitly apply those values to the wrapped standard elements. Because Python's `ui.element().props()` accepts a single string argument, format strings or string concatenation is required (e.g., `f'aria-label="{tooltip}"'`). Missing this pattern results in the aria-label missing from the rendered DOM despite being declared in the component constructor.
**Action:** When creating reusable UI sub-components in NiceGUI, add explicit parameter arguments for accessibility props (like `tooltip` and `aria-label`) and ensure they are bound to the inner `ui.element` utilizing `f-strings` or format syntax if they are dynamic.
