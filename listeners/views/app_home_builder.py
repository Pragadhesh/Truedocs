def _relative_time(iso_str: str) -> str:
    """Convert a UTC ISO timestamp to a human-readable relative string."""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        seconds = int((now - dt).total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            m = seconds // 60
            return f"{m} minute{'s' if m != 1 else ''} ago"
        if seconds < 86400:
            h = seconds // 3600
            return f"{h} hour{'s' if h != 1 else ''} ago"
        if seconds < 86400 * 2:
            return "yesterday"
        if seconds < 86400 * 7:
            d = seconds // 86400
            return f"{d} days ago"
        return dt.strftime(f"%b {dt.day}")
    except Exception:
        return iso_str[:10]


def build_app_home_view(
    install_url: str | None = None,
    is_connected: bool = False,
    creds: dict | None = None,
    processes: list[dict] | None = None,
) -> dict:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Truedocs"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Keep your runbooks honest — watches Slack and tells you when docs drift from reality.",
            },
        },
        {"type": "divider"},
    ]

    # ── Confluence Setup ────────────────────────────────────────────────────
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*Confluence Setup*"},
    })

    if creds:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":large_green_circle: *Credentials saved* — {creds['confluence_email']}",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit Credentials"},
                "action_id": "configure_confluence",
            },
        })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":red_circle: *Not configured.* Connect Confluence before registering processes.",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Configure Confluence"},
                "action_id": "configure_confluence",
                "style": "primary",
            },
        })

    blocks.append({"type": "divider"})

    # ── Registered Processes (only shown after Confluence is set) ──────────
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*Registered Processes*"},
    })

    if not creds:
        # Gate: must configure Confluence first
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_Configure Confluence above before registering processes._",
            },
        })
    else:
        # Show register button
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "+ Register new process"},
                    "action_id": "register_new_process",
                    "style": "primary",
                }
            ],
        })

        if processes:
            for proc in processes:
                trigger_label = _trigger_label(proc)
                last_seen = proc.get("last_observed_at") or ""
                drift = proc.get("drift_detected", False)
                status_line = (
                    f"Last scanned: {_relative_time(last_seen)}  ·  "
                    f"{'Drift found :rotating_light:' if drift else 'No drift :white_check_mark:'}"
                    if last_seen
                    else "_Never scanned_"
                )

                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*{proc['name']}*\n"
                            f"<#{proc['channel_id']}> · {trigger_label}\n"
                            f"{status_line}"
                        ),
                    },
                })
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Edit"},
                            "action_id": "edit_process",
                            "value": proc["id"],
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Delete"},
                            "action_id": "delete_process",
                            "value": proc["id"],
                            "style": "danger",
                            "confirm": {
                                "title": {"type": "plain_text", "text": "Delete process?"},
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"Remove *{proc['name']}* permanently?",
                                },
                                "confirm": {"type": "plain_text", "text": "Delete"},
                                "deny": {"type": "plain_text", "text": "Cancel"},
                            },
                        },
                    ],
                })
                blocks.append({"type": "divider"})
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_No processes registered yet._",
                },
            })

    return {"type": "home", "blocks": blocks}


def _trigger_label(proc: dict) -> str:
    t = proc.get("trigger_type", "manual")
    if t == "manual":
        return "Manual · use `/truedocs-scan` in channel"
    if t == "daily":
        return f"Daily · {proc.get('trigger_time', '09:00')}"
    if t == "weekly":
        day = (proc.get("trigger_day") or "monday").capitalize()
        return f"Weekly · Every {day} {proc.get('trigger_time', '09:00')}"
    return t
