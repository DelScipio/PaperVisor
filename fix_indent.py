with open("papervisor/ui/components/top_bar.py", "r") as f:
    content = f.read()

content = content.replace(
"""with ui.button(icon="notifications", on_click=on_open_inbox).props(
                    'dense flat round aria-label="Open notifications inbox"'
                ).classes("pv-topbar-btn") as inbox_button:""",
"""                with ui.button(icon="notifications", on_click=on_open_inbox).props(
                    'dense flat round aria-label="Open notifications inbox"'
                ).classes("pv-topbar-btn") as inbox_button:"""
)
with open("papervisor/ui/components/top_bar.py", "w") as f:
    f.write(content)
