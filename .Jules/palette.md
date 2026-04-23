## 2026-04-23 - Accessibility for top nav buttons
**Learning:** The main top navigation bar used icon-only buttons (Menu, Filters, Inbox, Upload, Settings, Profile, Logout) which lacked proper accessibility labels. Using `.props('aria-label="..."')` and `.tooltip('...')` significantly improves navigation clarity for screen readers and visual users.
**Action:** Whenever creating icon-only buttons, always ensure an `aria-label` property and a `.tooltip()` are added by default.
