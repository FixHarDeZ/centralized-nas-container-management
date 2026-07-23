# ops-bot/app/watchtower.py
import logging

from app.config import get_config
from app.ssh_client import get_ssh_client

logger = logging.getLogger(__name__)


async def is_watchtower_update(container_name: str) -> bool:
    """Check if watchtower recently updated this container."""
    cfg = get_config()
    ssh = get_ssh_client()

    minutes = cfg.watchtower_grace_minutes
    result = await ssh.execute_command(
        f"docker logs watchtower --since {minutes}m 2>&1 | grep -i '{container_name}'"
    )

    if result.exit_code == 0 and result.stdout.strip():
        logger.info(
            f"Watchtower recently updated {container_name}, "
            f"skipping alert (grace period: {minutes}m)"
        )
        return True

    return False
