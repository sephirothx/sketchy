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
            words.append("skeleton in a closet")
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
