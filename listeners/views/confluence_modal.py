def build_confluence_modal(prefill: dict | None = None) -> dict:
    """Modal for entering workspace-level Confluence API credentials.

    Only asks for email and API token — the Confluence base URL is
    inferred from each process's page URL when accessed.
    """
    p = prefill or {}

    def _iv(key: str) -> dict:
        val = p.get(key)
        return {"initial_value": val} if val else {}

    return {
        "type": "modal",
        "callback_id": "confluence_credentials_modal",
        "title": {"type": "plain_text", "text": "Connect Confluence"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Enter your Atlassian credentials. TrueDocs will use these to read and update Confluence pages on your behalf.",
                },
            },
            {
                "type": "input",
                "block_id": "confluence_email_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "confluence_email",
                    "placeholder": {"type": "plain_text", "text": "you@company.com"},
                    **_iv("confluence_email"),
                },
                "label": {"type": "plain_text", "text": "Atlassian Email"},
            },
            {
                "type": "input",
                "block_id": "confluence_token_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "confluence_token",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "API token from Atlassian",
                    },
                },
                "label": {"type": "plain_text", "text": "API Token"},
                "hint": {
                    "type": "plain_text",
                    "text": "Generate one at id.atlassian.com → Security → API tokens",
                },
            },
        ],
    }
