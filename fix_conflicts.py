import re

# Fix .Jules/palette.md
with open(".Jules/palette.md", "r") as f:
    content = f.read()

# For the palette.md, I will keep both learnings as they are both relevant to accessibility
# and UX, but in different contexts (general vs reusable components).
resolved_palette = """## 2026-04-29 - Accessibility of Icon-Only Navigation Buttons
**Learning:** Standard NiceGUI `ui.button(icon=...)` components used in global navigation structures (like the top bar) lack both visual hover context and screen-reader semantics by default, making them inaccessible to keyboard/assistive users and ambiguous to mouse users.
**Action:** Always append explicit `.props('aria-label="<Action Name>"')` for Quasar ARIA compliance and chain `.tooltip('<Action Name>')` for visual context whenever creating icon-only buttons in NiceGUI, particularly in navigation or toolbar areas.

## 2024-05-18 - Component Abstraction Props Iteration
**Learning:** When passing `aria-label` or `tooltip` strings as props into NiceGUI abstracted sub-components (like `_render_corner_toggle_button`), you must remember to explicitly apply those values to the wrapped standard elements. Because Python's `ui.element().props()` accepts a single string argument, format strings or string concatenation is required (e.g., `f'aria-label="{tooltip}"'`). Missing this pattern results in the aria-label missing from the rendered DOM despite being declared in the component constructor.
**Action:** When creating reusable UI sub-components in NiceGUI, add explicit parameter arguments for accessibility props (like `tooltip` and `aria-label`) and ensure they are bound to the inner `ui.element` utilizing `f-strings` or format syntax if they are dynamic.
"""

with open(".Jules/palette.md", "w") as f:
    f.write(resolved_palette)


# Fix papervisor/ui/components/top_bar.py
with open("papervisor/ui/components/top_bar.py", "r") as f:
    content = f.read()

# Merge conflict resolution for top_bar.py
# I will prefer origin/main's specific aria-labels ("Toggle navigation menu", "Toggle filters")
# but keep the structure clean

# Block 1: menu button
content = re.sub(
    r'<<<<<<< HEAD\n\s*\'dense flat round aria-label="Toggle Menu"\'\n\s*\)\.classes\("pv-topbar-btn"\)\.tooltip\("Toggle Menu"\)\n\n\s*if on_toggle_filters is not None:\n\s*ui\.button\(icon="tune", on_click=on_toggle_filters\)\.props\(\n\s*\'dense flat round aria-label="Toggle Filters"\'\n=======\n\s*\'dense flat round aria-label="Toggle navigation menu"\'\n\s*\)\.classes\("pv-topbar-btn"\)\.tooltip\("Navigation Menu"\)\n\n\s*if on_toggle_filters is not None:\n\s*ui\.button\(icon="tune", on_click=on_toggle_filters\)\.props\(\n\s*\'dense flat round aria-label="Toggle filters"\'\n>>>>>>> origin/main',
    """'dense flat round aria-label="Toggle navigation menu"'
                ).classes("pv-topbar-btn").tooltip("Navigation Menu")

            if on_toggle_filters is not None:
                ui.button(icon="tune", on_click=on_toggle_filters).props(
                    'dense flat round aria-label="Toggle filters"'""",
    content
)

# Block 2: brand button
content = re.sub(
    r'<<<<<<< HEAD\n\s*\.props\("flat dense no-caps"\)\n\s*\.classes\("px-3 py-1 pv-brand-btn"\)\n=======\n\s*\.props\(\'flat dense no-caps aria-label="Go to home"\'\)\n\s*\.classes\("px-3 py-1 pv-brand-btn"\)\n\s*\.tooltip\("Home"\)\n>>>>>>> origin/main',
    """.props('flat dense no-caps aria-label="Go to home"')
                .classes("px-3 py-1 pv-brand-btn")
                .tooltip("Home")""",
    content
)

# Block 3: inbox & upload
content = re.sub(
    r'<<<<<<< HEAD\n\s*with \(\n\s*ui\.button\(icon="notifications", on_click=on_open_inbox\)\n\s*\.props\(\'dense flat round aria-label="Open Inbox"\'\)\n\s*\.classes\("pv-topbar-btn"\)\n\s*\.tooltip\("Open Inbox"\)\n\s*\):\n\s*if count > 0:\n\s*ui\.badge\(str\(count\)\)\.props\(\'color="primary"\'\)\.classes\("pv-chip"\)\n\n\s*import_handler = on_import or \(lambda: None\)\n\s*ui\.button\(icon="cloud_upload", on_click=import_handler\)\.props\(\n\s*\'dense flat round aria-label="Upload PDF"\'\n\s*\)\.classes\("pv-topbar-btn"\)\.tooltip\("Upload PDF"\)\n=======\n\s*with ui\.button\(icon="notifications", on_click=on_open_inbox\)\.props\(\n\s*\'dense flat round aria-label="Open notifications inbox"\'\n\s*\)\.classes\("pv-topbar-btn"\) as inbox_button:\n\s*if count > 0:\n\s*ui\.badge\(str\(count\)\)\.props\(\'color="primary"\'\)\.classes\("pv-chip"\)\n\s*inbox_button\.tooltip\("Notifications"\)\n\n\s*import_handler = on_import or \(lambda: None\)\n\s*ui\.button\(icon="cloud_upload", on_click=import_handler\)\.props\(\n\s*\'dense flat round aria-label="Import files"\'\n\s*\)\.classes\("pv-topbar-btn"\)\.tooltip\("Import Files"\)\n>>>>>>> origin/main',
    """with ui.button(icon="notifications", on_click=on_open_inbox).props(
                    'dense flat round aria-label="Open notifications inbox"'
                ).classes("pv-topbar-btn") as inbox_button:
                    if count > 0:
                        ui.badge(str(count)).props('color="primary"').classes("pv-chip")
                inbox_button.tooltip("Notifications")

            import_handler = on_import or (lambda: None)
            ui.button(icon="cloud_upload", on_click=import_handler).props(
                'dense flat round aria-label="Import files"'
            ).classes("pv-topbar-btn").tooltip("Import Files")""",
    content
)

# Block 4: settings
content = re.sub(
    r'<<<<<<< HEAD\n\s*\)\.props\(\'dense flat round aria-label="Admin Settings"\'\)\.classes\(\n=======\n\s*\)\.props\(\'dense flat round aria-label="Open admin settings"\'\)\.classes\(\n>>>>>>> origin/main',
    """).props('dense flat round aria-label="Open admin settings"').classes(""",
    content
)

# Block 5: person & logout
content = re.sub(
    r'<<<<<<< HEAD\n\s*\'dense flat round aria-label="User Profile"\'\n\s*\)\.classes\("pv-topbar-btn"\)\.tooltip\("User Profile"\)\n\n\s*if on_logout is not None:\n\s*ui\.button\(icon="logout", on_click=on_logout\)\.props\(\n\s*\'dense flat round aria-label="Logout"\'\n\s*\)\.classes\("pv-topbar-btn"\)\.tooltip\("Logout"\)\n=======\n\s*\'dense flat round aria-label="Open profile"\'\n\s*\)\.classes\("pv-topbar-btn"\)\.tooltip\("Profile"\)\n\n\s*if on_logout is not None:\n\s*ui\.button\(icon="logout", on_click=on_logout\)\.props\(\n\s*\'dense flat round aria-label="Log out"\'\n\s*\)\.classes\("pv-topbar-btn"\)\.tooltip\("Log out"\)\n>>>>>>> origin/main',
    """'dense flat round aria-label="Open profile"'
                ).classes("pv-topbar-btn").tooltip("Profile")

            if on_logout is not None:
                ui.button(icon="logout", on_click=on_logout).props(
                    'dense flat round aria-label="Log out"'
                ).classes("pv-topbar-btn").tooltip("Log out")""",
    content
)

with open("papervisor/ui/components/top_bar.py", "w") as f:
    f.write(content)
