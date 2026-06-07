from slack_sdk import WebClient

from listeners.views.register_modal import build_register_modal


def handle_truedocs_command(ack, body: dict, client: WebClient):
    """Handle /truedocs [register] slash command."""
    subcommand = (body.get("text") or "").strip().lower()

    if subcommand in ("register", ""):
        ack()
        client.views_open(
            trigger_id=body["trigger_id"],
            view=build_register_modal(),
        )
    else:
        ack(f"Unknown subcommand `{subcommand}`. Try `/truedocs register`.")
