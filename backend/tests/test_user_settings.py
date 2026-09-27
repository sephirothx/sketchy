"""Cross-device registered-account settings and boundary validation."""
from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.user_settings import (
    DEFAULT_KEY_BINDINGS,
    UserSettingsSeed,
    create_user_settings_router,
    seed_user_settings,
)
from app.api.errors import install_refusal_handler
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import UserSettings
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db


PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "settings-test-secret")
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_user_settings_router(factory))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, factory
    await engine.dispose()


async def test_guests_remain_local_only(env):
    http, factory = env
    guest = (
        await http.post("/api/auth/display-name", json={"displayName": "Visitor"})
    ).json()
    response = await http.get("/api/users/me/settings")
    assert response.status_code == 403
    async with factory() as session:
        assert await session.get(UserSettings, UUID(guest["id"])) is None


async def test_registration_seeds_and_patch_persists_settings(env):
    http, factory = env
    seeded = {
        "theme": "dark",
        "soundEffects": False,
        "confettiEffects": False,
        "volume": 0.35,
        "brushCursor": "circle",
        # Off, against a default of on: a seed that was dropped would read back true.
        "penPressure": False,
        "defaultBrushSize": 12,
        "keyBindings": {**DEFAULT_KEY_BINDINGS, "brush": ["b"]},
        "colorblindSafeColors": True,
        "timeFormat": "24h",
        # Two languages, and they are not the same one: this account plays in
        # English and reads in German (R-I18N-06).
        "promptLanguage": "en",
        "locale": "de",
    }
    registered = await http.post(
        "/api/auth/register",
        json={
            "username": "SettingsOwner",
            "password": PASSWORD,
            "settings": seeded,
        },
    )
    assert registered.status_code == 200

    loaded = await http.get("/api/users/me/settings")
    assert loaded.status_code == 200
    for key, value in seeded.items():
        assert loaded.json()[key] == value

    patched = await http.patch(
        "/api/users/me/settings",
        json={"theme": "light", "volume": 0.9},
    )
    assert patched.status_code == 200
    assert patched.json()["theme"] == "light"
    assert patched.json()["volume"] == 0.9
    assert patched.json()["brushCursor"] == "circle"
    assert patched.json()["penPressure"] is False

    turned_on = await http.patch("/api/users/me/settings", json={"penPressure": True})
    assert turned_on.status_code == 200
    assert turned_on.json()["penPressure"] is True
    assert (await http.patch("/api/users/me/settings", json={"penPressure": "yes please"})).status_code == 422

    async with factory() as session:
        row = await session.scalar(select(UserSettings))
        assert row is not None
        assert row.theme == "light"
        assert row.sound_effects_volume == 0.9
        assert row.pen_pressure is True


async def test_the_default_brush_size_is_one_of_the_sliders_stops(env):
    """A default the slider could not show would be a size nobody can get back to."""
    http, factory = env
    registered = await http.post(
        "/api/auth/register", json={"username": "SizeDefault", "password": PASSWORD}
    )
    assert registered.status_code == 200
    assert (await http.get("/api/users/me/settings")).json()["defaultBrushSize"] == 6

    patched = await http.patch("/api/users/me/settings", json={"defaultBrushSize": 24})
    assert patched.status_code == 200
    assert patched.json()["defaultBrushSize"] == 24
    # 6.0 is not here: JSON has one number type, and it is stored as 6.
    for refused in (5, 0, 64, "6", 6.5, True, [6]):
        response = await http.patch("/api/users/me/settings", json={"defaultBrushSize": refused})
        assert response.status_code == 422, refused
    async with factory() as session:
        row = await session.scalar(select(UserSettings))
        assert row.default_brush_size == 24


async def test_pen_pressure_is_on_until_a_player_turns_it_off(env):
    """It only ever acts for a pressure-sensitive pen, so a player with one
    gets it without looking for it (#828)."""
    http, _ = env
    registered = await http.post(
        "/api/auth/register", json={"username": "PenDefault", "password": PASSWORD}
    )
    assert registered.status_code == 200
    assert (await http.get("/api/users/me/settings")).json()["penPressure"] is True


async def test_registration_seed_never_overwrites_existing_settings(env):
    http, factory = env
    registered = await http.post(
        "/api/auth/register",
        json={
            "username": "SeedOnce",
            "password": PASSWORD,
            "settings": {"theme": "dark"},
        },
    )
    assert registered.status_code == 200
    existing = await seed_user_settings(
        factory,
        user_id=registered.json()["id"],
        values=UserSettingsSeed(theme="light"),
    )
    assert existing["theme"] == "dark"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"theme": "sepia"},
        {"volume": -0.01},
        {"volume": 1.01},
        {"brushCursor": "dot"},
        {"timeFormat": "13h"},
        {"locale": "kl"},
        {"locale": "en-GB"},
        {"keyBindings": {"brush": ["b"]}},
        {"extraPromptLanguages": ["de", "de"]},
        {"extraPromptLanguages": ["kl"]},
        {"extraPromptLanguages": ["mul"]},
        {"extraPromptLanguages": ["zxx"]},
        {"extraPromptLanguages": "de"},
        {"extraPromptLanguages": ["de", "es", "fr", "it", "nl", "pt", "en"]},
        # The default is English; naming it among the others as well is two
        # answers to one question.
        {"extraPromptLanguages": ["de", "en"]},
        {"promptLanguage": "de", "extraPromptLanguages": ["de"]},
    ],
)
async def test_patch_rejects_invalid_or_unbounded_values(env, body):
    http, _ = env
    assert (
        await http.post(
            "/api/auth/register",
            json={"username": "Validation", "password": PASSWORD},
        )
    ).status_code == 200
    response = await http.patch("/api/users/me/settings", json=body)
    assert response.status_code == 422


async def test_the_two_languages_are_kept_apart(env):
    """Playing in one language and reading in another is ordinary.

    One column could not describe it, and a change to either must leave the
    other exactly where it was (R-I18N-06).
    """
    http, factory = env
    assert (
        await http.post(
            "/api/auth/register",
            json={
                "username": "TwoLanguages",
                "password": PASSWORD,
                "settings": {"promptLanguage": "en", "locale": "nl"},
            },
        )
    ).status_code == 200

    changed = await http.patch("/api/users/me/settings", json={"locale": "de"})
    assert changed.status_code == 200
    assert changed.json() == {**changed.json(), "locale": "de", "promptLanguage": "en"}

    changed = await http.patch("/api/users/me/settings", json={"promptLanguage": "fr"})
    assert changed.status_code == 200
    assert changed.json()["locale"] == "de", "the room language moved the interface"
    assert changed.json()["promptLanguage"] == "fr"

    async with factory() as session:
        row = await session.scalar(select(UserSettings))
        assert row is not None
        assert (row.locale, row.prompt_language) == ("de", "fr")


async def test_database_checks_reject_invalid_theme_and_volume(env):
    http, factory = env
    registered = await http.post(
        "/api/auth/register",
        json={"username": "DbChecks", "password": PASSWORD},
    )
    user_id = UUID(registered.json()["id"])
    async with factory() as session:
        async with session.begin():
            row = await session.get(UserSettings, user_id)
            assert row is not None
            await session.delete(row)

    async with factory() as session:
        async with session.begin():
            defaults = UserSettings(user_id=user_id)
            session.add(defaults)
            await session.flush()
            assert defaults.theme == "system"
            assert defaults.sound_effects_volume == 0.7
            assert defaults.key_bindings == DEFAULT_KEY_BINDINGS
            await session.delete(defaults)

    with pytest.raises(IntegrityError):
        async with factory() as session:
            async with session.begin():
                session.add(
                    UserSettings(
                        user_id=user_id,
                        theme="sepia",
                        sound_effects_volume=2,
                    )
                )


async def test_me_carries_a_registered_accounts_settings_and_a_guest_none(env):
    """The page holds its first paint for `/me` (R-I18N-06), so a registered
    account's settings ride along rather than costing a second round trip
    (#983). A guest has no stored settings, and is not given any."""
    http, _ = env
    await http.post("/api/auth/display-name", json={"displayName": "Visitor"})
    guest = (await http.get("/api/auth/me")).json()
    assert "settings" not in guest

    registered = await http.post(
        "/api/auth/register",
        json={
            "username": "MeSettings",
            "password": PASSWORD,
            "settings": {"theme": "dark", "locale": "it", "penPressure": False},
        },
    )
    assert registered.status_code == 200

    me = (await http.get("/api/auth/me")).json()
    assert me["settings"] == (await http.get("/api/users/me/settings")).json()
    assert me["settings"]["locale"] == "it"
    assert me["settings"]["theme"] == "dark"


async def test_me_still_answers_when_the_settings_read_fails(env, monkeypatch):
    """The session may have rotated earlier in the same request; failing the
    whole answer would drop the new cookie with the old token already revoked.
    Without settings the page fetches them on their own."""
    http, _ = env
    registered = await http.post(
        "/api/auth/register", json={"username": "MeResilient", "password": PASSWORD}
    )
    assert registered.status_code == 200

    async def unavailable(*args, **kwargs):
        raise RuntimeError("database busy")

    monkeypatch.setattr("app.auth.routes.settings_of_registered_account", unavailable)
    me = await http.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "MeResilient"
    assert "settings" not in me.json()


async def _register(http, username: str, settings: dict | None = None) -> None:
    body = {"username": username, "password": PASSWORD}
    if settings is not None:
        body["settings"] = settings
    assert (await http.post("/api/auth/register", json=body)).status_code == 200


async def test_an_account_plays_a_default_and_other_languages_in_order(env):
    """#1209: the default, then the others in the order the player ranked
    them - kept exactly, since the lobby ranks their rooms by it."""
    http, factory = env
    await _register(
        http,
        "Polyglot",
        {"promptLanguage": "it", "extraPromptLanguages": ["nl", "en"]},
    )
    loaded = (await http.get("/api/users/me/settings")).json()
    assert (loaded["promptLanguage"], loaded["extraPromptLanguages"]) == ("it", ["nl", "en"])

    reordered = await http.patch(
        "/api/users/me/settings", json={"extraPromptLanguages": ["en", "nl", "pt"]}
    )
    assert reordered.status_code == 200
    assert reordered.json()["extraPromptLanguages"] == ["en", "nl", "pt"]

    cleared = await http.patch("/api/users/me/settings", json={"extraPromptLanguages": []})
    assert cleared.json()["extraPromptLanguages"] == []
    async with factory() as session:
        row = await session.scalar(select(UserSettings))
        assert (row.prompt_language, row.extra_prompt_languages) == ("it", [])


async def test_an_account_that_never_chose_plays_one_language(env):
    http, _ = env
    await _register(http, "OneLanguage")
    loaded = (await http.get("/api/users/me/settings")).json()
    assert loaded["extraPromptLanguages"] == []


async def test_promoting_another_language_swaps_the_default_into_its_place(env):
    """Choosing one of the others as the default loses nothing: the old
    default takes its place in the order. A default from outside the list
    replaces the old one, as a single language always did."""
    http, _ = env
    await _register(
        http,
        "Promoter",
        {"promptLanguage": "it", "extraPromptLanguages": ["nl", "en", "es"]},
    )
    promoted = (await http.patch("/api/users/me/settings", json={"promptLanguage": "en"})).json()
    assert (promoted["promptLanguage"], promoted["extraPromptLanguages"]) == ("en", ["nl", "it", "es"])

    replaced = (await http.patch("/api/users/me/settings", json={"promptLanguage": "fr"})).json()
    assert (replaced["promptLanguage"], replaced["extraPromptLanguages"]) == ("fr", ["nl", "it", "es"])

    # Sent together, the pair is taken as sent.
    both = (
        await http.patch(
            "/api/users/me/settings",
            json={"promptLanguage": "nl", "extraPromptLanguages": ["fr"]},
        )
    ).json()
    assert (both["promptLanguage"], both["extraPromptLanguages"]) == ("nl", ["fr"])


async def test_naming_the_default_among_the_others_is_refused_against_that_field(env):
    http, _ = env
    await _register(http, "Twice", {"promptLanguage": "de"})
    refused = await http.patch(
        "/api/users/me/settings", json={"extraPromptLanguages": ["en", "de"]}
    )
    assert refused.status_code == 422
    assert refused.json()["field"] == "extraPromptLanguages"
    assert (await http.get("/api/users/me/settings")).json()["extraPromptLanguages"] == []


async def test_a_browser_copy_naming_its_default_twice_still_registers(env):
    """The seed is the browser's copy becoming the account's (R-SET-03); a
    registration is not refused over it, and the default is what it meant."""
    http, _ = env
    await _register(
        http,
        "SeedTwice",
        {"promptLanguage": "pt", "extraPromptLanguages": ["pt", "es", "es"]},
    )
    loaded = (await http.get("/api/users/me/settings")).json()
    assert (loaded["promptLanguage"], loaded["extraPromptLanguages"]) == ("pt", ["es"])

    # Every language, the default among them: six others once it is dropped,
    # which is the bound - counted after, not before.
    await http.post("/api/auth/logout")
    await _register(
        http,
        "SeedEvery",
        {
            "promptLanguage": "pt",
            "extraPromptLanguages": ["en", "de", "pt", "es", "fr", "it", "nl"],
        },
    )
    loaded = (await http.get("/api/users/me/settings")).json()
    assert loaded["extraPromptLanguages"] == ["en", "de", "es", "fr", "it", "nl"]


async def test_two_devices_at_once_never_list_the_default_twice(env):
    """One device ranks a language among the others while another makes it
    the default. Whichever lands second must see the first: on PostgreSQL the
    row lock makes it read what the first wrote (so it is refused, or swaps);
    on SQLite, which has no row lock, the CHECK refuses the second write, and
    the refusal is the same one. No order may store the default among the
    others."""
    import asyncio

    http, factory = env
    await _register(
        http,
        "TwoDevices",
        {"promptLanguage": "it", "extraPromptLanguages": ["en", "nl"]},
    )
    for _ in range(5):
        ranked, promoted = await asyncio.gather(
            http.patch("/api/users/me/settings", json={"extraPromptLanguages": ["fr", "en"]}),
            http.patch("/api/users/me/settings", json={"promptLanguage": "fr"}),
        )
        assert {ranked.status_code, promoted.status_code} <= {200, 422}
        async with factory() as session:
            row = await session.scalar(select(UserSettings))
            assert row.prompt_language not in row.extra_prompt_languages, (
                row.prompt_language,
                row.extra_prompt_languages,
            )
        reset = await http.patch(
            "/api/users/me/settings",
            json={"promptLanguage": "it", "extraPromptLanguages": ["en", "nl"]},
        )
        assert reset.status_code == 200


async def test_the_database_holds_the_default_out_of_the_other_languages(env):
    """What a JSON column can be held to on both engines: a short list, never
    naming the default. The routes check it first; this is what holds when two
    of them both passed that check against the same row."""
    http, factory = env
    await _register(http, "DbLanguages", {"promptLanguage": "de"})
    for extras in (["de"], ["en", "de"], "de", {"de": 1}, ["en"] * 9):
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    row = await session.scalar(select(UserSettings))
                    row.extra_prompt_languages = extras
    async with factory() as session:
        async with session.begin():
            row = await session.scalar(select(UserSettings))
            row.extra_prompt_languages = ["en", "es", "fr", "it", "nl", "pt"]
    async with factory() as session:
        row = await session.scalar(select(UserSettings))
        assert row.extra_prompt_languages == ["en", "es", "fr", "it", "nl", "pt"]


async def test_a_seed_carries_the_other_languages_over_a_row_another_tab_made(env):
    """R-SET-03: the browser's copy becomes the account's even when another tab
    made a defaults row first - the other languages included."""
    http, factory = env
    registered = await http.post(
        "/api/auth/register", json={"username": "OtherTab", "password": PASSWORD}
    )
    user_id = registered.json()["id"]
    async with factory() as session:
        async with session.begin():
            row = await session.get(UserSettings, UUID(user_id))
            row.email_reminder_last_shown_at = None
            row.extra_prompt_languages = []
    seeded = await seed_user_settings(
        factory,
        user_id=user_id,
        values=UserSettingsSeed(promptLanguage="de", extraPromptLanguages=["fr", "it"]),
    )
    assert (seeded["promptLanguage"], seeded["extraPromptLanguages"]) == ("de", ["fr", "it"])
