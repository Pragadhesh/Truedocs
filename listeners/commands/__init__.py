from slack_bolt import App

from .truedocs_register import handle_truedocs_command


def register(app: App):
    app.command("/truedocs")(handle_truedocs_command)
