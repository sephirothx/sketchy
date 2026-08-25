def base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = digits[remainder] + result
    return result or "0"


def maximum_custom_prompts() -> list[str]:
    words = []
    for index in range(10_000):
        token = base36(index).rjust(3, "0")
        if index % 3 == 0:
            words.append(f"s{token}")
        elif index % 3 == 1:
            words.append(f"medium{token}")
        elif index == 2:
            # Long enough to always truncate inside a virtual-grid cell (the
            # bundled Nunito Sans makes text metrics deterministic), while the
            # single-result search view still shows it in full.
            words.append("skeleton in a closet somewhere")
        else:
            words.append(f"long-custom-{'W' * 17}{token}")
    return words


async def set_textarea_value(page, selector: str, value: str) -> None:
    await page.locator(selector).evaluate(
        """(element, nextValue) => {
            const setter = Object.getOwnPropertyDescriptor(
                HTMLTextAreaElement.prototype,
                "value",
            ).set;
            setter.call(element, nextValue);
            element.dispatchEvent(new Event("input", { bubbles: true }));
        }""",
        value,
    )
