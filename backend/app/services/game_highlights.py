"""Pick the few moments from a finished game worth putting on the final screen.

Kept apart from `GameFlowService` for the same reason `game_history.py` is: no
sockets, no database, no timers - just a mapping from what the game remembers to
what the room is shown. That matters more here than it looks. The game history
write is optional and is deliberately allowed to fail (see
`GameFlowService._persist_game_history`), so a highlight derived from the
database would go missing exactly when the database is having a bad day. These
are read straight off `Game.completed_turns`, which is in memory and complete by
the time the game ends.

Every highlight here is derived from guess counts and timings alone - or, for
the most-reacted drawing, from what the room reacted to. None of them reads
points, so all of them mean the same thing in a no-scoring game as in a scored
one, and the final screen needs no second `scoring_mode` branch.

The most-reacted drawing is the one highlight that can change after the game
ends, because a reaction can be given from the recap. It is therefore built
from the `Room` alone - the recap entries and the reactions on them - so it
can be recomputed once `room.game` is gone; `refresh_reaction_highlight` does
that in place.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.game import Game
from app.rooms import Room

# A drawer's turns are only comparable against another drawer's. With one
# qualifying drawer the "best" of them is just the only one of them.
MIN_RANKED_DRAWERS = 2

# An average over a single guess is that guess. Both a floor on one player's
# sample and a floor on how many players there are to rank.
MIN_GUESSES_FOR_AVERAGE = 2
MIN_RANKED_GUESSERS = 2


@dataclass(frozen=True, slots=True)
class _Name:
    """How one roster token's name should render."""

    nickname: str
    name_color: str | None
    is_anonymous: bool


def _resolve_names(room: Room) -> dict[str, _Name]:
    """Map every roster token the room can still name to how it renders.

    Deliberately *not* `game_history._resolve_seats`. That one drops spectators
    and seats with no `user_id`, which is correct for a database write keyed on
    a NOT NULL user id and wrong here: a player whose browser blocked the
    session cookie has no account, still played the whole game, and can still
    hold the fastest guess of it.

    Departed seats are included so a player who left before the final screen is
    still named on it.
    """
    names: dict[str, _Name] = {}
    for token, player in room.players.items():
        names[token] = _Name(
            nickname=player.nickname,
            name_color=player.name_color,
            is_anonymous=player.is_anonymous,
        )
    for token, seat in room.departed_seats.items():
        names.setdefault(
            token,
            _Name(
                nickname=seat.nickname,
                name_color=seat.name_color,
                is_anonymous=seat.is_anonymous,
            ),
        )
    return names


def _named(highlight: dict, name: _Name) -> dict:
    """Attach the three fields the client renders a player name from."""
    return {
        **highlight,
        "nickname": name.nickname,
        "nameColor": name.name_color,
        "isAnonymous": name.is_anonymous,
    }


def _hardest_prompt(game: Game) -> dict | None:
    """The prompt the smallest share of its guessers got.

    Turns nobody could have guessed - no eligible guessers at all - are not
    hard, they are empty, and they are excluded rather than ranked at zero.
    """
    candidates = [t for t in game.completed_turns if t.total_guesser_count > 0]
    if not candidates:
        return None
    turn = min(
        candidates,
        key=lambda t: (
            t.correct_guess_count / t.total_guesser_count,
            t.correct_guess_count,
            t.turn_number,
        ),
    )
    # Everyone got everything, so no prompt was harder than any other. Naming
    # one anyway would claim a difficulty that the game did not show.
    if turn.correct_guess_count >= turn.total_guesser_count:
        return None
    return {
        "kind": "hardest_prompt",
        "prompt": turn.chosen_prompt,
        "correctGuessCount": turn.correct_guess_count,
        "totalGuesserCount": turn.total_guesser_count,
    }


def _fastest_guess(game: Game, names: dict[str, _Name]) -> dict | None:
    """The single quickest correct guess of the game."""
    best = None
    for turn in game.completed_turns:
        for guess in turn.guesses:
            if guess.token not in names:
                continue
            if best is None or guess.guess_time_seconds < best[0].guess_time_seconds:
                best = (guess, turn)
    if best is None:
        return None
    guess, turn = best
    return _named(
        {
            "kind": "fastest_guess",
            "prompt": turn.chosen_prompt,
            "seconds": round(guess.guess_time_seconds, 2),
        },
        names[guess.token],
    )


def _best_drawer(game: Game, names: dict[str, _Name]) -> dict | None:
    """The drawer whose prompts the largest share of guessers got."""
    ratios: dict[str, list[float]] = {}
    for turn in game.completed_turns:
        if turn.total_guesser_count <= 0 or turn.drawer_token not in names:
            continue
        ratios.setdefault(turn.drawer_token, []).append(
            turn.correct_guess_count / turn.total_guesser_count
        )
    if len(ratios) < MIN_RANKED_DRAWERS:
        return None
    token = max(
        ratios,
        key=lambda t: (sum(ratios[t]) / len(ratios[t]), len(ratios[t])),
    )
    best = sum(ratios[token]) / len(ratios[token])
    # Everyone ties at zero in a game where nothing was guessed, and the winner
    # of that tie is a drawer nobody ever got. There is no best drawer here.
    if best <= 0:
        return None
    return _named(
        {"kind": "best_drawer", "guessRatio": round(best, 4)},
        names[token],
    )


def _quickest_on_average(game: Game, names: dict[str, _Name]) -> dict | None:
    """The player whose correct guesses came quickest across the whole game."""
    times: dict[str, list[float]] = {}
    for turn in game.completed_turns:
        for guess in turn.guesses:
            if guess.token not in names:
                continue
            times.setdefault(guess.token, []).append(guess.guess_time_seconds)
    ranked = {
        token: values
        for token, values in times.items()
        if len(values) >= MIN_GUESSES_FOR_AVERAGE
    }
    if len(ranked) < MIN_RANKED_GUESSERS:
        return None
    token = min(ranked, key=lambda t: sum(ranked[t]) / len(ranked[t]))
    return _named(
        {
            "kind": "quickest_average",
            "seconds": round(sum(ranked[token]) / len(ranked[token]), 2),
        },
        names[token],
    )


MOST_REACTED_KIND = "most_reacted_drawing"


def _most_reacted_drawing(room: Room, names: dict[str, _Name]) -> dict | None:
    """The drawing the room reacted to most; the earliest one on a tie.

    Zero reactions is not a highlight. The count is of reactions, not of
    reactors' points, so it means the same in every scoring mode.
    """
    best: tuple[int, int] | None = None
    for index, entry in enumerate(room.last_game_drawings):
        count = len(room.drawing_reactions.get(entry.turn_id, {}))
        if count <= 0:
            continue
        if best is None or count > best[0]:
            best = (count, index)
    if best is None:
        return None
    count, index = best
    entry = room.last_game_drawings[index]
    name = names.get(entry.drawer_id) or _Name(
        nickname=entry.drawer_nickname,
        name_color=entry.drawer_name_color,
        is_anonymous=False,
    )
    return _named(
        {
            "kind": MOST_REACTED_KIND,
            "prompt": entry.prompt,
            "reactionCount": count,
            "drawingIndex": index,
            "turnId": entry.turn_id,
        },
        name,
    )


def refresh_reaction_highlight(room: Room) -> None:
    """Recompute the most-reacted card in `room.last_game_highlights`, in place.

    Replaces the existing card where it stands, appends one when reactions
    first arrive, and removes it when the last reaction is taken back, so the
    other highlights keep their order.
    """
    fresh = _most_reacted_drawing(room, _resolve_names(room))
    highlights = room.last_game_highlights
    position = next(
        (i for i, item in enumerate(highlights) if item.get("kind") == MOST_REACTED_KIND),
        None,
    )
    if fresh is None:
        if position is not None:
            del highlights[position]
    elif position is None:
        highlights.append(fresh)
    else:
        highlights[position] = fresh


def build_game_highlights(room: Room, game: Game) -> list[dict]:
    """The finished game's highlights, in the order they should be shown.

    Each one is dropped on its own when the game gives it nothing to say, so a
    short or lopsided game shows fewer rather than showing an empty superlative.
    A game with no completed turns produces none at all.
    """
    names = _resolve_names(room)
    candidates = (
        _hardest_prompt(game),
        _fastest_guess(game, names),
        _best_drawer(game, names),
        _quickest_on_average(game, names),
        _most_reacted_drawing(room, names),
    )
    return [highlight for highlight in candidates if highlight is not None]
