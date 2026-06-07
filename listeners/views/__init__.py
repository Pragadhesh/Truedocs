from slack_bolt import App


def register(app: App):
    # Lazy imports break the actions ↔ views circular dependency
    from listeners.actions.confluence_setup import (
        handle_confluence_credentials_submission,
    )
    from listeners.actions.register_process import handle_register_process_submission

    app.view("confluence_credentials_modal")(handle_confluence_credentials_submission)
    app.view("register_process_modal")(handle_register_process_submission)
