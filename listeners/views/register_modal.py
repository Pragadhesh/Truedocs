_LOOKBACK_OPTIONS = [
    {"text": {"type": "plain_text", "text": "Last 1 hour"}, "value": "1h"},
    {"text": {"type": "plain_text", "text": "Last 4 hours"}, "value": "4h"},
    {"text": {"type": "plain_text", "text": "Last 12 hours"}, "value": "12h"},
    {"text": {"type": "plain_text", "text": "Last 1 day"}, "value": "1d"},
    {"text": {"type": "plain_text", "text": "Last 1 week"}, "value": "1w"},
]

_TRIGGER_OPTIONS = [
    {
        "text": {"type": "plain_text", "text": "Manual phrase"},
        "description": {
            "type": "plain_text",
            "text": "Someone types a keyword in the channel",
        },
        "value": "manual",
    },
    {
        "text": {"type": "plain_text", "text": "Daily schedule"},
        "description": {"type": "plain_text", "text": "Runs every day at a set time"},
        "value": "daily",
    },
    {
        "text": {"type": "plain_text", "text": "Weekly schedule"},
        "description": {
            "type": "plain_text",
            "text": "Runs every week on a set day and time",
        },
        "value": "weekly",
    },
]

_DAY_OPTIONS = [
    {"text": {"type": "plain_text", "text": day.capitalize()}, "value": day}
    for day in [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
]


def build_register_modal(
    trigger_type: str | None = None,
    prefill: dict | None = None,
    process_id: str | None = None,
    lookback_window: str | None = None,
) -> dict:
    """Build the Register a Process modal.

    Pass trigger_type to show the matching conditional input block.
    Pass prefill to restore text fields when rebuilding after trigger_type change.
    """
    p = prefill or {}
    lookback_window = lookback_window or p.get("lookback_window") or "1d"

    def _iv(key: str) -> dict:
        val = p.get(key)
        return {"initial_value": val} if val else {}

    radio_element: dict = {
        "type": "radio_buttons",
        "action_id": "trigger_type",
        "options": _TRIGGER_OPTIONS,
    }
    if trigger_type:
        matched = next((o for o in _TRIGGER_OPTIONS if o["value"] == trigger_type), None)
        if matched:
            radio_element["initial_option"] = matched

    channel_element: dict = {
        "type": "channels_select",
        "action_id": "channel_id",
        "placeholder": {"type": "plain_text", "text": "Select a channel"},
    }
    if p.get("channel_id"):
        channel_element["initial_channel"] = p["channel_id"]

    blocks: list[dict] = [
        {
            "type": "input",
            "block_id": "process_name_block",
            "element": {
                "type": "plain_text_input",
                "action_id": "process_name",
                "placeholder": {"type": "plain_text", "text": "Deploy to Production"},
                **_iv("process_name"),
            },
            "label": {"type": "plain_text", "text": "Process Name"},
        },
        {
            "type": "input",
            "block_id": "confluence_page_url_block",
            "element": {
                "type": "plain_text_input",
                "action_id": "confluence_page_url",
                "placeholder": {
                    "type": "plain_text",
                    "text": "https://company.atlassian.net/wiki/spaces/ENG/pages/...",
                },
                **_iv("confluence_page_url"),
            },
            "label": {"type": "plain_text", "text": "Confluence Page URL"},
        },
        {
            "type": "input",
            "block_id": "channel_block",
            "element": channel_element,
            "label": {"type": "plain_text", "text": "Slack Channel"},
        },
        {
            "type": "input",
            "block_id": "lookback_window_block",
            "element": {
                "type": "static_select",
                "action_id": "lookback_window",
                "options": _LOOKBACK_OPTIONS,
                "initial_option": next(
                    o for o in _LOOKBACK_OPTIONS if o["value"] == lookback_window
                ),
            },
            "label": {"type": "plain_text", "text": "Observation Window"},
            "hint": {
                "type": "plain_text",
                "text": "TrueDocs reads all channel messages within this window when triggered",
            },
        },
        {
            "type": "input",
            "block_id": "trigger_type_block",
            "dispatch_action": True,
            "element": radio_element,
            "label": {"type": "plain_text", "text": "Trigger Type"},
        },
    ]

    # Conditional blocks
    if trigger_type == "manual":
        blocks.append(
            {
                "type": "section",
                "block_id": "trigger_phrase_block",
                "text": {
                    "type": "mrkdwn",
                    "text": ":zap: *Trigger phrase:* `run-truedocs`\nType this in the channel to start a documentation check.",
                },
            }
        )
    elif trigger_type == "daily":
        blocks.append(
            {
                "type": "input",
                "block_id": "trigger_time_block",
                "element": {
                    "type": "timepicker",
                    "action_id": "trigger_time",
                    "placeholder": {"type": "plain_text", "text": "Select time"},
                    "initial_time": "09:00",
                },
                "label": {"type": "plain_text", "text": "Run observation at"},
            }
        )
    elif trigger_type == "weekly":
        blocks.extend(
            [
                {
                    "type": "input",
                    "block_id": "trigger_day_block",
                    "element": {
                        "type": "static_select",
                        "action_id": "trigger_day",
                        "placeholder": {"type": "plain_text", "text": "Select day"},
                        "options": _DAY_OPTIONS,
                    },
                    "label": {"type": "plain_text", "text": "Day of week"},
                },
                {
                    "type": "input",
                    "block_id": "trigger_time_block",
                    "element": {
                        "type": "timepicker",
                        "action_id": "trigger_time",
                        "placeholder": {"type": "plain_text", "text": "Select time"},
                        "initial_time": "09:00",
                    },
                    "label": {"type": "plain_text", "text": "Time"},
                },
            ]
        )

    modal: dict = {
        "type": "modal",
        "callback_id": "register_process_modal",
        "title": {
            "type": "plain_text",
            "text": "Edit Process" if process_id else "Register a Process",
        },
        "submit": {
            "type": "plain_text",
            "text": "Save" if process_id else "Register",
        },
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }
    if process_id:
        modal["private_metadata"] = process_id
    return modal
