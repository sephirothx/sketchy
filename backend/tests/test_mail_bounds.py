"""What one inbox can be sent, whoever asks and from wherever (#1240).

The only bounds on reset and verification mail were per address, and the
caller chooses whose inbox: from one /64, twenty reset mails reached one
player - each retiring the link before it - and from one account twenty-five
verification mails reached an address that had never heard of Sketchy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.auth.mail import MemoryTransport, deliver_pending, queue_email
from app.domain_values import EmailTemplate

from tests.test_account_recovery import PASSWORD, drain, register, token_in
from tests.test_address_keys import build_site


def addresses(count: int) -> list[str]:
    """Callers on as many different /64s."""
    return [f"2001:db8:{index + 1:x}::1" for index in range(count)]


async def verified_account(from_address, factory, name: str, email: str) -> None:
    http = from_address("198.51.100.200")
    await register(http, name, email=email)
    transport = await drain(factory)
    assert (await http.post("/api/auth/email/verify", json={"token": token_in(transport)})).status_code == 200


async def test_resets_to_one_account_are_bounded_whatever_the_address(monkeypatch):
    async with build_site(monkeypatch, IP_HASH_SECRET="mail-bounds") as from_address:
        factory = from_address.factory
        await verified_account(from_address, factory, "Victim", "victim@example.test")

        answers = [
            await from_address(host).post("/api/auth/password/forgot", json={"identifier": "Victim"})
            for host in addresses(5)
        ]
        stranger = await from_address("2001:db8:ff::1").post(
            "/api/auth/password/forgot", json={"identifier": "NobodyAtAll"}
        )
        sent = (await drain(factory)).sent

        assert {answer.status_code for answer in answers} == {200}
        assert all(answer.json() == stranger.json() for answer in answers)
        assert [message.to_address for message in sent] == ["victim@example.test"] * 3
        # The refused requests retired nothing: the last link mailed works.
        check = await from_address("2001:db8:fe::1").post(
            "/api/auth/password/reset/check", json={"token": token_in_message(sent[-1])}
        )
        assert check.json() == {"valid": True}


async def test_the_daily_reset_bound_holds_after_the_hour_is_spent(monkeypatch):
    async with build_site(
        monkeypatch, IP_HASH_SECRET="mail-bounds",
        AUTH_RESET_ACCOUNT_LIMIT=100, AUTH_RESET_ACCOUNT_DAILY_LIMIT=4,
    ) as from_address:
        factory = from_address.factory
        await verified_account(from_address, factory, "Daily", "daily@example.test")
        for host in addresses(6):
            await from_address(host).post("/api/auth/password/forgot", json={"identifier": "daily@example.test"})
        assert len((await drain(factory)).sent) == 4


async def test_verification_mail_to_one_recipient_is_bounded_across_accounts(monkeypatch):
    async with build_site(monkeypatch, IP_HASH_SECRET="mail-bounds") as from_address:
        factory = from_address.factory
        accounts = []
        for index, host in enumerate(addresses(3)):
            http = from_address(host)
            await register(http, f"Sender{index}")
            accounts.append(http)
        await drain(factory)

        answers = [
            await http.put("/api/auth/email", json={"email": "target@example.test", "password": PASSWORD})
            for http in accounts
            for _ in range(2)
        ]
        sent = (await drain(factory)).sent

        assert {answer.status_code for answer in answers} == {200}
        assert {tuple(answer.json().items()) for answer in answers} == {
            (("ok", True), ("pendingAddress", "target@example.test"))
        }
        assert [message.to_address for message in sent] == ["target@example.test"] * 3


async def test_a_resend_past_the_bound_keeps_the_link_already_sent(monkeypatch):
    async with build_site(monkeypatch, IP_HASH_SECRET="mail-bounds") as from_address:
        factory = from_address.factory
        http = from_address("2001:db8:a::1")
        await register(http, "Resender")
        sent = []
        for _ in range(4):
            await http.put("/api/auth/email", json={"email": "mine@example.test", "password": PASSWORD})
            sent.extend((await drain(factory)).sent)
        assert len(sent) == 3

        proved = await http.post("/api/auth/email/verify", json={"token": token_in_message(sent[-1])})
        assert proved.status_code == 200


async def test_one_account_may_ask_to_verify_only_so_many_addresses_a_day(monkeypatch):
    async with build_site(monkeypatch, IP_HASH_SECRET="mail-bounds") as from_address:
        factory = from_address.factory
        http = from_address("2001:db8:b::1")
        await register(http, "Scatter")
        codes = [
            (await http.put(
                "/api/auth/email", json={"email": f"someone{index}@example.test", "password": PASSWORD}
            )).status_code
            for index in range(7)
        ]
        assert codes == [200] * 5 + [429] * 2
        assert len((await drain(factory)).sent) == 5


async def test_a_wrong_password_spends_nothing_of_the_day(monkeypatch):
    async with build_site(monkeypatch, IP_HASH_SECRET="mail-bounds", AUTH_VERIFY_ACCOUNT_LIMIT=1) as from_address:
        http = from_address("2001:db8:c::1")
        await register(http, "Typo")
        wrong = await http.put("/api/auth/email", json={"email": "t@example.test", "password": "not it at all"})
        right = await http.put("/api/auth/email", json={"email": "t@example.test", "password": PASSWORD})
        assert wrong.status_code != 200 and right.status_code == 200


async def test_a_reset_is_claimed_before_older_verification_mail(monkeypatch):
    async with build_site(monkeypatch, IP_HASH_SECRET="mail-bounds") as from_address:
        factory = from_address.factory
        earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
        async with factory() as session, session.begin():
            for index in range(5):
                queue_email(
                    session, to_address=f"flood{index}@example.test", template=EmailTemplate.VERIFY_EMAIL,
                    payload={"token": "t", "displayName": "x"}, now=earlier + timedelta(seconds=index),
                )
            queue_email(
                session, to_address="locked-out@example.test", template=EmailTemplate.RESET_PASSWORD,
                payload={"token": "t", "displayName": "x"},
            )
        transport = MemoryTransport()
        await deliver_pending(factory, transport=transport, base_url="http://test", batch_size=2)
        assert "locked-out@example.test" in [message.to_address for message in transport.sent]


def token_in_message(message) -> str:
    return message.body.split("token=")[1].split()[0].strip()


async def test_a_flood_of_resets_still_leaves_verification_mail_a_share(monkeypatch):
    """#1302 review: every due reset went before any verification, so a queue
    that never ran dry of resets held verification mail until its link had
    expired. A share of each batch is kept for everything else."""
    async with build_site(monkeypatch, IP_HASH_SECRET="mail-bounds") as from_address:
        factory = from_address.factory
        earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
        async with factory() as session, session.begin():
            queue_email(
                session, to_address="waiting@example.test", template=EmailTemplate.VERIFY_EMAIL,
                payload={"token": "t", "displayName": "x"}, now=earlier,
            )
            for index in range(20):
                queue_email(
                    session, to_address=f"reset{index}@example.test", template=EmailTemplate.RESET_PASSWORD,
                    payload={"token": "t", "displayName": "x"},
                )
        transport = MemoryTransport()
        await deliver_pending(factory, transport=transport, base_url="http://test", batch_size=5)
        sent = [message.to_address for message in transport.sent]
        assert "waiting@example.test" in sent
        assert len(sent) == 5 and sum(address.startswith("reset") for address in sent) == 4


async def test_a_one_message_batch_still_reaches_a_waiting_reset(monkeypatch):
    """#1302 review: the share for other mail had a floor of one, so a
    one-message batch always went to other mail while any was due, and a
    reset behind a steady trickle of it was never sent."""
    async with build_site(monkeypatch, IP_HASH_SECRET="mail-bounds") as from_address:
        factory = from_address.factory
        start = datetime.now(timezone.utc) - timedelta(minutes=10)
        async with factory() as session, session.begin():
            queue_email(
                session, to_address="locked-out@example.test", template=EmailTemplate.RESET_PASSWORD,
                payload={"token": "t", "displayName": "x"}, now=start,
            )
        sent = []
        for index in range(3):
            # Other mail keeps arriving, each newer than the reset.
            async with factory() as session, session.begin():
                queue_email(
                    session, to_address=f"verify{index}@example.test", template=EmailTemplate.VERIFY_EMAIL,
                    payload={"token": "t", "displayName": "x"}, now=start + timedelta(minutes=index + 1),
                )
            transport = MemoryTransport()
            await deliver_pending(factory, transport=transport, base_url="http://test", batch_size=1)
            sent += [message.to_address for message in transport.sent]
        assert sent[0] == "locked-out@example.test"
        assert sent[1:] == ["verify0@example.test", "verify1@example.test"]


async def test_a_small_batch_still_keeps_a_slot_for_other_mail(monkeypatch):
    """#1302 review: batches of two to four kept no slot for other mail, so a
    backlog of older resets held verification mail until it expired."""
    async with build_site(monkeypatch, IP_HASH_SECRET="mail-bounds") as from_address:
        factory = from_address.factory
        start = datetime.now(timezone.utc) - timedelta(minutes=10)
        async with factory() as session, session.begin():
            for index in range(6):
                queue_email(
                    session, to_address=f"reset{index}@example.test", template=EmailTemplate.RESET_PASSWORD,
                    payload={"token": "t", "displayName": "x"}, now=start + timedelta(seconds=index),
                )
            queue_email(
                session, to_address="waiting@example.test", template=EmailTemplate.VERIFY_EMAIL,
                payload={"token": "t", "displayName": "x"}, now=start + timedelta(minutes=5),
            )
        transport = MemoryTransport()
        await deliver_pending(factory, transport=transport, base_url="http://test", batch_size=2)
        sent = [message.to_address for message in transport.sent]
        # Which reset is not the point - queued in one transaction, they share
        # a created_at on PostgreSQL - only that one of the two slots is not.
        assert "waiting@example.test" in sent
        assert len(sent) == 2 and sum(address.startswith("reset") for address in sent) == 1
