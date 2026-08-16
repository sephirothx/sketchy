import pytest


@pytest.fixture
def assert_input_contract():
    async def assert_contract(locator, expected):
        contract = await locator.evaluate(
            """(input) => ({
                type: input.type,
                role: input.getAttribute("role"),
                inputMode: input.inputMode,
                autoComplete: input.getAttribute("autocomplete"),
                autoCapitalize: input.getAttribute("autocapitalize"),
                spellCheck: input.spellcheck,
                autoCorrect: input.getAttribute("autocorrect"),
                enterKeyHint: input.enterKeyHint,
            })"""
        )
        assert {key: contract[key] for key in expected} == expected

    return assert_contract
