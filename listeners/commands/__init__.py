from slack_bolt import App

from .truedocs_register import handle_truedocs_scan_command
from .ask import handle_truedocs_ask_command


def register(app: App):
    app.command("/truedocs-scan")(handle_truedocs_scan_command)
    app.command("/truedocs-ask")(handle_truedocs_ask_command)
