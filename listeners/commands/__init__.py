from slack_bolt import App

from .truedocs_register import handle_truedocs_command, handle_truedocs_run_command


def register(app: App):
    app.command("/truedocs")(handle_truedocs_command)
    app.command("/truedocs-run")(handle_truedocs_run_command)
