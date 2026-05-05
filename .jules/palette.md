## 2024-04-30 - Top Navigation Accessibility
**Learning:** Adding both `.tooltip()` and `aria-label` properties to Quasar icon-only buttons in NiceGUI (`ui.button(icon=...)`) ensures that UI actions are both discoverable by sighted users via hover text and properly communicated to screen readers. For top-level navigation elements where the surrounding visual context might be insufficient, explicit text alternatives are especially important.
**Action:** When implementing icon-only buttons in NiceGUI, combine `.tooltip("Label")` and `.props('aria-label="Label"')`.
