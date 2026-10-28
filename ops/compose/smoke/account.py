"""The account half of the Compose smoke (#405), from outside, as a player.

A guest takes a name, registers with an email address, and the confirmation
mail must reach the relay (mailpit here, a real relay in production). Then
it asks for its data export, waits for it, downloads and reads it, and
deletes the account, after which the session must be gone.

Standard library only, so it runs on whatever Python the host has:

    python3 ops/compose/smoke/account.py --base-url http://127.0.0.1:18080 \
        --mail-api http://127.0.0.1:18025

Exit status 0 when every step passed, 1 with the step that failed otherwise.
"""
from __future__ import annotations

import argparse
import gzip
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class SmokeFailure(Exception):
    pass


def request(method: str, url: str, *, body=None, cookie: str | None = None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    sent = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        sent["Content-Type"] = "application/json"
    if cookie:
        sent["Cookie"] = cookie
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=sent), timeout=20) as response:  # noqa: S310 - the smoke names the URL
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def session_cookie(headers, previous: str | None = None) -> str | None:
    """The session cookie a response set, as `name=value`, or the previous one."""
    for value in headers.get_all("Set-Cookie") or []:
        pair = value.split(";", 1)[0]
        if "sketchy_session=" in pair:
            return pair
    return previous


def expect(status: int, wanted: int, step: str, body: bytes) -> None:
    if status != wanted:
        raise SmokeFailure(f"{step}: answered {status}, expected {wanted}: {body[:300]!r}")


def run(base: str, mail_api: str) -> None:
    suffix = secrets.token_hex(3)
    username = f"smoke_{suffix}"
    password = f"compose-smoke-{secrets.token_hex(12)}"
    email = f"smoke-{suffix}@sketchy-smoke.org"

    status, headers, body = request("POST", f"{base}/api/auth/display-name", body={"displayName": f"Smoke-{suffix}"})
    expect(status, 200, "guest", body)
    cookie = session_cookie(headers)
    if not cookie:
        raise SmokeFailure("guest: no session cookie was set")

    status, headers, body = request(
        "POST", f"{base}/api/auth/register", cookie=cookie,
        body={"username": username, "password": password, "email": email},
    )
    expect(status, 200, "register", body)
    cookie = session_cookie(headers, cookie)
    print(f"ok: registered {username}")

    # The confirmation mail leaves through the outbox, which wakes on commit.
    deadline = time.monotonic() + 60
    while True:
        status, _, body = request("GET", f"{mail_api}/api/v1/search?query={urllib.parse.quote('to:' + email)}")
        if status == 200 and json.loads(body).get("messages_count", 0) >= 1:
            break
        if time.monotonic() > deadline:
            raise SmokeFailure(f"mail: no message to {email} reached the relay within 60 s")
        time.sleep(1)
    print("ok: the confirmation mail reached the relay")

    status, _, body = request("POST", f"{base}/api/auth/data-exports", cookie=cookie)
    expect(status, 202, "export request", body)
    export_id = json.loads(body)["id"]
    deadline = time.monotonic() + 120
    while True:
        status, _, body = request("GET", f"{base}/api/auth/data-exports/{export_id}", cookie=cookie)
        expect(status, 200, "export status", body)
        job = json.loads(body)
        if job["status"] == "ready":
            break
        if job["status"] == "failed":
            raise SmokeFailure(f"export: failed with {job.get('failureCode')}")
        if time.monotonic() > deadline:
            raise SmokeFailure(f"export: still {job['status']} after 120 s")
        time.sleep(1)
    status, headers, body = request(
        "GET", f"{base}/api/auth/data-exports/{export_id}/download", cookie=cookie,
        headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
    )
    expect(status, 200, "export download", body)
    if headers.get("Content-Encoding") == "gzip":
        body = gzip.decompress(body)
    document = json.loads(body)
    if not isinstance(document, dict) or username not in body.decode("utf-8"):
        raise SmokeFailure("export: the document does not name the account it belongs to")
    print(f"ok: export downloaded ({len(body)} bytes)")

    status, _, body = request("DELETE", f"{base}/api/auth/account", cookie=cookie, body={"password": password})
    expect(status, 200, "delete account", body)
    status, _, body = request("GET", f"{base}/api/auth/me", cookie=cookie)
    expect(status, 200, "me after delete", body)
    if json.loads(body or b"null") is not None:
        raise SmokeFailure("delete account: the session still names an account")
    print("ok: account deleted, session gone")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--mail-api", required=True, help="mailpit's HTTP address")
    args = parser.parse_args()
    try:
        run(args.base_url.rstrip("/"), args.mail_api.rstrip("/"))
    except SmokeFailure as failure:
        print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
