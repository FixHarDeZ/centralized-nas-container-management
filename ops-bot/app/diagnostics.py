# ops-bot/app/diagnostics.py
import logging
from typing import Optional, Tuple

from app.ssh_client import get_ssh_client

logger = logging.getLogger(__name__)

DIAGNOSTIC_STEPS = [
    {
        "name": "container_status",
        "commands": [
            "docker ps -a --filter 'name={container}' --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'",
            "docker inspect {container} --format '{{json .State}}'",
            "docker logs --tail 100 {container} 2>&1",
        ],
    },
    {
        "name": "system_resources",
        "commands": [
            "df -h / /volume2 2>/dev/null",
            "free -m",
            "uptime",
            "cat /proc/loadavg",
        ],
    },
    {
        "name": "container_config",
        "commands": [
            "docker inspect {container} --format 'mem_limit={{.HostConfig.Memory}} cpu_quota={{.HostConfig.CpuQuota}} restart_policy={{.HostConfig.RestartPolicy.Name}}'",
        ],
    },
    {
        "name": "service_health",
        "commands": [
            "docker inspect {container} --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'",
            "docker port {container}",
        ],
    },
    {
        "name": "network_diagnostics",
        "commands": [
            "docker inspect {container} --format '{{json .NetworkSettings.Networks}}'",
        ],
    },
    {
        "name": "compose_logs",
        "commands": [],  # Handled dynamically via find_compose_file
    },
]


async def find_compose_file(container_name: str) -> Optional[Tuple[str, str]]:
    ssh = get_ssh_client()

    # Get compose project dir from container label
    result = await ssh.execute_command(
        f"docker inspect {container_name} --format '{{{{index .Config.Labels \"com.docker.compose.project.working_dir\"}}}}'"
    )
    if result.exit_code != 0 or not result.stdout.strip():
        return None

    compose_dir = result.stdout.strip()

    # Get compose file name
    result = await ssh.execute_command(
        f"docker inspect {container_name} --format '{{{{index .Config.Labels \"com.docker.compose.project.config_files\"}}}}'"
    )
    compose_file = result.stdout.strip() if result.exit_code == 0 and result.stdout.strip() else "docker-compose.yml"

    return compose_dir, compose_file


async def run_diagnostics(container_name: str) -> dict[str, str]:
    ssh = get_ssh_client()
    results = {}

    for step in DIAGNOSTIC_STEPS:
        step_outputs = []
        for cmd_template in step["commands"]:
            cmd = cmd_template.format(container=container_name)
            result = await ssh.execute_command(cmd)
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr] {result.stderr}"
            step_outputs.append(f"$ {cmd}\n{output}")

        results[step["name"]] = "\n\n".join(step_outputs)

    # Compose logs (separate step — needs compose file discovery)
    compose_info = await find_compose_file(container_name)
    if compose_info:
        compose_dir, compose_file = compose_info
        result = await ssh.execute_command(
            f"docker compose -f {compose_dir}/{compose_file} logs --tail 100 2>&1"
        )
        results["compose_logs"] = f"$ docker compose logs\n{result.stdout}"
    else:
        results["compose_logs"] = "(ไม่พบ docker-compose.yml)"

    return results
