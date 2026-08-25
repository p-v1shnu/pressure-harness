"""Container commands.

A container is a way to run something under different rules than the host's,
which is precisely the thing this policy engine decides. Judging `docker` as one
opaque program means `docker exec api rm -rf /` reads as two harmless words.

Every refusal here was reachable before these rules existed: the whole set is a
regression suite for a hole found by asking whether the tool could manage
containers at all.
"""

from __future__ import annotations

import pytest

from pharness.adapters.posix.shell import PosixShell
from pharness.adapters.windows.shell import WindowsShell
from pharness.core.policy.commands import Tier, classify, container_verb

READ_ONLY_ALLOWLIST = [
    "docker ps",
    "docker images",
    "docker inspect",
    "docker compose ps",
    "docker compose logs",
    "docker compose up",
    "docker compose exec",
]


def judge(command: str, allow: list[str] | None = None) -> Tier:
    return classify(command, shell=PosixShell(), allow_commands=allow or READ_ONLY_ALLOWLIST).tier


def reason(command: str) -> str:
    return classify(command, shell=PosixShell(), allow_commands=READ_ONLY_ALLOWLIST).top_reason


# -- reading the verb ----------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "verb"),
    [
        ("docker ps", "ps"),
        ("docker compose up -d", "up"),
        ("docker compose down -v", "down"),
        ("docker system prune -af", "prune"),
        ("docker volume rm app_data", "rm"),
        ("docker -H tcp://x image prune", "prune"),
        ("docker", ""),
    ],
)
def test_the_verb_is_found_behind_the_noun(command: str, verb: str):
    """`system`, `volume` and `compose` say nothing; the next word says everything."""
    args = command.split()[1:]
    assert container_verb(args) == verb


# -- what must be refused ------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "docker run --rm -v /:/host alpine cat /host/etc/shadow",
        "docker run -v /etc:/etc alpine sh",
        "podman run -v /root:/root alpine sh",
    ],
)
def test_mounting_the_host_is_refused(command: str):
    """A mount like this reaches around the workspace entirely."""
    assert judge(command) is Tier.FORBIDDEN


@pytest.mark.parametrize(
    "command",
    [
        "docker run --privileged alpine sh",
        "docker run --pid=host alpine nsenter -t 1 -m sh",
        "docker run --pid host alpine sh",
        "docker run --userns=host alpine sh",
        "docker run --security-opt seccomp=unconfined alpine sh",
        "podman run --privileged alpine sh",
    ],
)
def test_giving_the_container_the_host_is_refused(command: str):
    assert judge(command) is Tier.FORBIDDEN


def test_mounting_the_docker_socket_is_refused():
    """Handing over the socket is handing over the machine."""
    command = "docker run -v /var/run/docker.sock:/var/run/docker.sock alpine sh"
    assert judge(command) is Tier.FORBIDDEN
    assert "socket" in reason(command)


@pytest.mark.parametrize(
    "command",
    [
        "docker run -v $HOME/.ssh:/keys alpine cat /keys/id_rsa",
        "docker run -v ~/.aws:/aws alpine sh",
        "docker run --mount type=bind,source=/home/dev/.gnupg,target=/g alpine sh",
    ],
)
def test_mounting_a_credential_directory_is_refused(command: str):
    """`$HOME` is never expanded here, so the name is what has to be recognised."""
    assert judge(command) is Tier.FORBIDDEN


@pytest.mark.parametrize(
    "command",
    [
        "docker volume rm app_pgdata",
        "docker volume prune -f",
        "docker compose down -v",
        "docker compose down --volumes",
        "docker system prune -af --volumes",
    ],
)
def test_destroying_volumes_is_refused(command: str):
    """The journal covers files. It has never covered a database volume."""
    assert judge(command) is Tier.FORBIDDEN


@pytest.mark.parametrize(
    "command",
    [
        "docker exec -u root api rm -rf /",
        "docker compose exec db sh -c 'rm -rf /var/lib/postgresql/data'",
        "docker run --rm alpine rm -rf /data",
        "docker compose run --rm api rm -rf node_modules",
    ],
)
def test_a_destructive_command_inside_a_container_is_still_destructive(command: str):
    assert judge(command) is Tier.FORBIDDEN
    assert "inside the container" in reason(command)


def test_the_windows_parser_reaches_the_same_verdict():
    assert classify("docker compose down -v", shell=WindowsShell()).tier is Tier.FORBIDDEN


# -- what must still work ------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "docker ps",
        "docker images",
        "docker inspect my-postgres",
        "docker compose ps",
        "docker compose logs -f api",
        "docker compose up -d",
    ],
)
def test_everyday_commands_can_be_allowlisted(command: str):
    """Prompting for `docker ps` is how people learn to approve without reading."""
    assert judge(command) is Tier.EXEC_ALLOWED


@pytest.mark.parametrize(
    "command",
    [
        "docker compose exec api npm run migrate",
        "docker compose exec -T db psql -U app -d app -f /migrations/001.sql",
        "docker compose exec api alembic upgrade head",
    ],
)
def test_migrations_run_when_the_workspace_allows_them(command: str):
    assert judge(command) is Tier.EXEC_ALLOWED


@pytest.mark.parametrize(
    "command",
    ["docker start db", "docker stop db", "docker compose restart api", "docker rm old"],
)
def test_ordinary_lifecycle_commands_ask(command: str):
    assert judge(command) is Tier.EXEC_OTHER


@pytest.mark.parametrize("command", ["docker pull postgres:16", "docker build -t app ."])
def test_pulling_and_building_count_as_reaching_out(command: str):
    """A build runs whatever the Dockerfile says, and fetches what it names."""
    assert judge(command) is Tier.EGRESS


def test_an_ordinary_project_mount_is_not_treated_as_an_escape(command: str = ""):
    """`-v ./src:/app` is the normal case and must not be refused."""
    assert judge("docker run -v ./src:/app node:20 npm test") is Tier.EXEC_OTHER
    assert judge("docker compose down") is Tier.EXEC_OTHER
