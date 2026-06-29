from slack_bolt import App

from .feedback_buttons import handle_feedback_button
from .confluence_setup import (
    handle_configure_confluence,
    handle_confluence_credentials_submission,
)
from .register_process import (
    handle_open_register_modal,
    handle_edit_process,
    handle_trigger_type_change,
    handle_register_process_submission,
    handle_delete_process,
)
from .drift_actions import (
    handle_approve_drift,
    handle_reject_drift,
    handle_approve_drift_item,
    handle_reject_drift_item,
)
from .ask_scan_action import handle_run_scan_from_ask


def register(app: App):
    app.action("feedback")(handle_feedback_button)
    app.action("configure_confluence")(handle_configure_confluence)
    app.action("register_new_process")(handle_open_register_modal)
    app.action("edit_process")(handle_edit_process)
    app.action("trigger_type")(handle_trigger_type_change)
    app.action("delete_process")(handle_delete_process)
    app.action("approve_drift")(handle_approve_drift)
    app.action("reject_drift")(handle_reject_drift)
    app.action("approve_drift_item")(handle_approve_drift_item)
    app.action("reject_drift_item")(handle_reject_drift_item)
    app.action("run_scan_from_ask")(handle_run_scan_from_ask)
