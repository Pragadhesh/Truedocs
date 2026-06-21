import logging
from slack_sdk import WebClient

logger = logging.getLogger(__name__)

ADMIN_ONLY_MSG = ":lock: Only workspace admins can perform this action."


def is_workspace_admin(client: WebClient, user_id: str) -> bool:
    try:
        resp = client.users_info(user=user_id)
        user = resp["user"]
        return user.get("is_admin", False) or user.get("is_owner", False)
    except Exception:
        logger.warning("Could not verify admin status for user %s", user_id)
        return False


def deny_non_admin(client: WebClient, user_id: str, channel_id: str | None = None) -> None:
    """Post an ephemeral (or DM) telling the user they need admin rights."""
    if channel_id:
        try:
            client.chat_postEphemeral(channel=channel_id, user=user_id, text=ADMIN_ONLY_MSG)
            return
        except Exception:
            pass
    client.chat_postMessage(channel=user_id, text=ADMIN_ONLY_MSG)
