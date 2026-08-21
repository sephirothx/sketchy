from app.prompts import MAX_PROMPT_LENGTH, parse_custom_prompt_list


def test_parse_custom_word_list_accepts_lines_and_commas():
    assert parse_custom_prompt_list("apple\nred panda, banana\r\nAPPLE") == ["apple", "red panda", "banana"]


def test_parse_custom_word_list_discards_overlong_and_blank_entries():
    overlong = "x" * (MAX_PROMPT_LENGTH + 1)
    assert parse_custom_prompt_list(f"apple, , {overlong}\nbanana") == ["apple", "banana"]
