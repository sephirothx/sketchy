"""The Compose deployment keeps the properties it was written for (#405).

`ops/compose/smoke/smoke.sh` proves the stack by running it, in a workflow
that only runs when the deployment files change. This keeps the cheap part on
every pull request: the properties that hold by what the files say, and that
a well-meant edit elsewhere (a second copy of the initdb flags, a port opened
to debug something, an `env_file` to save typing) could quietly undo.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "ops" / "compose" / "compose.yaml"


def services() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def test_the_cluster_is_created_with_the_tracked_initdb_flags():
    """Compose cannot read ops/postgres/initdb.args, so it carries a copy; the
    copy must not drift, because the flags cannot be changed after initdb."""
    tracked = " ".join(
        line
        for line in (ROOT / "ops" / "postgres" / "initdb.args").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ).split()
    assert services()["db"]["environment"]["POSTGRES_INITDB_ARGS"].split() == tracked


def test_nothing_is_published_to_the_host():
    """The tunnel is the only way in: a published port is reachable from the
    home network and arrives through the gateway, past the trusted-proxy rule."""
    assert {name: service["ports"] for name, service in services().items() if "ports" in service} == {}


def test_each_service_is_given_its_variables_by_name():
    """An `env_file` hands every service every secret, the web process the
    schema owner's password with them (#896)."""
    assert [name for name, service in services().items() if "env_file" in service] == []
    app = services()["app"]["environment"]
    assert "MIGRATION_DATABASE_URL" not in app
    assert not any(value and "sketchy_owner" in str(value) for value in app.values())
    assert not any(name.startswith(("POSTGRES_", "SKETCHY_OWNER")) for name in app)
    assert "sketchy_app:" in app["DATABASE_URL"]
    assert "sketchy_owner:" in services()["migrate"]["environment"]["MIGRATION_DATABASE_URL"]


def test_forwarded_headers_are_trusted_from_the_tunnel_alone():
    """R-PLAT-10: one address, the tunnel's, never a subnet."""
    trusted = services()["app"]["environment"]["FORWARDED_ALLOW_IPS"]
    tunnel = services()["cloudflared"]["networks"]["edge"]["ipv4_address"]
    assert trusted == tunnel
    assert "/" not in trusted and "*" not in trusted


def test_no_other_container_can_be_handed_the_tunnels_address():
    """Dynamic addresses come from `ip_range`; the tunnel's must lie outside it."""
    def default(value: str) -> str:
        return re.fullmatch(r"\$\{\w+:-([^}]+)\}", value).group(1)

    network = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["networks"]["edge"]["ipam"]["config"][0]
    subnet = ipaddress.ip_network(default(network["subnet"]))
    dynamic = ipaddress.ip_network(default(network["ip_range"]))
    tunnel = ipaddress.ip_address(default(services()["cloudflared"]["networks"]["edge"]["ipv4_address"]))
    assert dynamic.subnet_of(subnet)
    assert tunnel in subnet and tunnel not in dynamic


def test_the_app_waits_for_its_migration_and_outlasts_its_drain():
    app = services()["app"]
    assert app["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    # Any drain the operator may set (R-SHUT-03), not only the default, plus
    # the 10 s history write, uvicorn's 15 s graceful shutdown and the forced
    # teardown's ceiling, must fit inside the grace before Docker kills it.
    from app.deployment import MAX_SHUTDOWN_DRAIN_SECONDS
    from app.server import FORCED_EXIT_TEARDOWN_SECONDS

    grace = int(re.fullmatch(r"(\d+)s", app["stop_grace_period"]).group(1))
    assert grace >= MAX_SHUTDOWN_DRAIN_SECONDS + 10 + 15 + FORCED_EXIT_TEARDOWN_SECONDS


def test_the_application_containers_run_unprivileged_and_read_only():
    for name in ("app", "migrate"):
        service = services()[name]
        assert service["read_only"] is True, name
        assert service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
        assert not str(service["user"]).startswith(("0:", "root")), name
    assert re.search(r"^USER 10001:10001$", (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.MULTILINE)


def test_the_database_and_its_dump_client_are_the_same_major_version():
    """pg_dump refuses a newer server, and the app needs 17 or later (#1367)."""
    server = re.fullmatch(r"postgres:(\d+)\.\d+-\w+", services()["db"]["image"]).group(1)
    client = re.search(r"postgresql-client-(\d+)", (ROOT / "Dockerfile").read_text(encoding="utf-8")).group(1)
    assert server == client
    assert int(server) >= 17


def test_the_image_is_built_from_an_allowlist():
    """A local database or .env must never reach a layer (#452)."""
    lines = [
        line
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert lines[0] == "*"
