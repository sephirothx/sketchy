"""Name lists: official prompt lists written once and expanded per language (#1399).

The seed format's keys (`answer`, `aliases`, `overrides`) are the files' in
`backend/data/prompt_lists`, not payloads; `tests/test_wire_contract.py`
exempts this module from its vocabulary scan for that reason. Pure: no I/O.
"""
from __future__ import annotations

from app.domain_values import PROMPT_LANGUAGES, PromptLanguage


def is_name_list(data: dict) -> bool:
    """Whether a seed file is a **name list** (#1399): written once, with a
    default spelling per concept and overrides where a language differs,
    rather than once per language."""
    return "languages" in data and "language" not in data


def expand_name_list(data: dict) -> list[dict]:
    """A name list as the per-language lists it stands for, each in the shape
    a one-language seed file has.

    Names - Pokémon, game characters - are mostly the same in every language,
    so writing them once spares a copy per language, and a language added to
    the registry gets them without one: each supported language is expanded
    whether or not the file names it, so the families mixed rooms pin stay
    whole. A language's spelling is its override where there is one - answer
    and aliases replaced together, and its own `promptVersion` if it gives
    one - and otherwise the default's. Whether each language was *checked* is
    the file's declaration (`languages.inherit` / `languages.override`),
    which `tests/test_bundled_prompt_content.py` holds to every supported
    language: a new one is a reviewed line, never a silent inheritance.
    """
    declared = data["languages"]
    inherit = set(declared.get("inherit", []))
    override = set(declared.get("override", []))
    unknown = (inherit | override) - set(PROMPT_LANGUAGES)
    if unknown:
        raise ValueError(f"name list {data['slug']} declares unsupported languages: {sorted(unknown)}")
    if inherit & override:
        raise ValueError(f"name list {data['slug']} declares {sorted(inherit & override)} twice")
    for prompt in data["prompts"]:
        stray = set(prompt.get("overrides", {})) - override
        if stray:
            raise ValueError(
                f"name list {data['slug']} overrides {sorted(stray)} for {prompt['answer']}, "
                "which it does not declare as overriding"
            )
    names = data.get("names", {})
    descriptions = data.get("descriptions", {})
    expanded = []
    for language in PROMPT_LANGUAGES:
        prompts = []
        for prompt in data["prompts"]:
            own = prompt.get("overrides", {}).get(language)
            source = own if own is not None else prompt
            entry = {"conceptId": prompt["conceptId"], "answer": source["answer"]}
            if source.get("aliases"):
                entry["aliases"] = list(source["aliases"])
            version = (own or {}).get("promptVersion", prompt.get("promptVersion"))
            if version is not None:
                entry["promptVersion"] = version
            for key in ("difficulty", "contentRating", "tags"):
                if key in prompt:
                    entry[key] = prompt[key]
            prompts.append(entry)
        body = {
            "slug": f"{PromptLanguage(language).name.lower()}_{data['slug']}",
            "name": names.get(language, data["name"]),
            "description": descriptions.get(language, data.get("description", "")),
            "language": language,
            "version": data.get("version", 1),
            "shelf": data["shelf"],
            "position": data.get("position", 0),
            "tags": list(data.get("tags", [])),
            "prompts": prompts,
        }
        if data.get("series") is not None:
            body["series"] = data["series"]
        expanded.append(body)
    return expanded
