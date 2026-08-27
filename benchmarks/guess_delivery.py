#!/usr/bin/env python3
"""What confirming a guess costs on the wire (#421).

`guess` is sent volatile, so a momentary unwritable transport drops it with no
feedback and no retry. Closing that hole needs two things: a correlation handle
so the client knows its guess landed, and an identifier so a retry cannot be
processed twice.

Two shapes were considered, and the point of this benchmark is that they are
not the same size:

  echo-matching  the issue's proposal - the client's `id` is echoed back inside
                 the `chat_message` the server already sends, so every socket in
                 the room carries the extra field.
  ack            the guess is emitted with a Socket.IO acknowledgement, which
                 correlates by packet id. The `id` field still travels up (the
                 server dedupes a retry on it) but nothing extra travels down
                 except an empty ACK packet to the one guesser.

Everything is measured through a permessage-deflate context with context
takeover, which is what the deployment negotiates - an uncompressed count would
badly overstate a repeated JSON key.

Usage:
  backend/.venv/bin/python benchmarks/guess_delivery.py
  backend/.venv/bin/python benchmarks/guess_delivery.py --players 16 --guesses 8
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import zlib

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from uuid import UUID

# A turn's worth of wrong guesses at one prompt, in the order a room produces
# them. Lengths and repetition are what deflate reacts to, so they are drawn
# from plausible play rather than filler.
GUESSES = [
    "cat", "dog", "horse", "a cat", "kitten", "lion", "tiger", "puppy",
    "bird", "fish", "mouse", "rabbit", "cats", "kitty", "panther", "cub",
]


def json_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def event_packet(event: str, payload, ack_id: int | None = None) -> bytes:
    """One Socket.IO EVENT packet, as it reaches the WebSocket."""
    prefix = b"42" if ack_id is None else b"42" + str(ack_id).encode()
    return prefix + json_bytes([event, payload])


def ack_packet(ack_id: int) -> bytes:
    """The ACK python-socketio sends for a handler that returns None."""
    return b"43" + str(ack_id).encode() + b"[]"


def deflated_stream_bytes(messages: list[bytes]) -> list[int]:
    """Per-message wire cost through one permessage-deflate context."""
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    return [
        len(compressor.compress(message) + compressor.flush(zlib.Z_SYNC_FLUSH))
        for message in messages
    ]


def stable_uuid(index: int) -> str:
    """A UUIDv7-shaped identifier that is the same on every run.

    The real ones are time-ordered and random. Two runs would then compress
    differently, and the two arms of the comparison would differ by more than
    the field under test - which is exactly the mistake this benchmark exists
    to avoid making about the protocol.
    """
    return str(UUID(int=(0x01234567_89AB_7000_8000_000000000000 + index * 0x9E3779B9)))


def chat_line(message_index: int, nickname: str, text: str) -> dict:
    """The `chat_message` a wrong guess broadcasts, as `_chat_line` builds it."""
    return {
        "playerId": stable_uuid(message_index * 2),
        "nickname": nickname,
        "text": text,
        "correct": False,
        "retainedMessageId": stable_uuid(message_index * 2 + 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=16)
    parser.add_argument("--guesses", type=int, default=8,
                        help="guesses one player sends in a turn")
    args = parser.parse_args()

    guesses = [GUESSES[i % len(GUESSES)] for i in range(args.guesses)]

    # --- Uplink: one guesser's own socket, one deflate context ---------------
    today_up = [event_packet("guess", {"text": text}) for text in guesses]
    confirmed_up = [
        event_packet("guess", {"text": text, "id": index}, ack_id=index)
        for index, text in enumerate(guesses)
    ]
    today_up_wire = deflated_stream_bytes(today_up)
    confirmed_up_wire = deflated_stream_bytes(confirmed_up)

    # --- Downlink: what one *other* socket in the room receives --------------
    # Every wrong guess in the room is echoed to it. Under echo-matching that
    # echo grows by the `id` field; under the ack it does not change at all.
    room_guessers = max(1, args.players - 1)
    room_echoes = [
        (f"Player_{index % room_guessers}", GUESSES[index % len(GUESSES)])
        for index in range(args.guesses * room_guessers)
    ]
    # Both arms are built from the *same* payloads, so the only difference
    # between the two streams is the field under test.
    base_echoes = [
        chat_line(index, nickname, text)
        for index, (nickname, text) in enumerate(room_echoes)
    ]
    today_down = [
        event_packet("chat_message", payload) for payload in base_echoes
    ]
    echoed_down = [
        event_packet("chat_message", {**payload, "id": index})
        for index, payload in enumerate(base_echoes)
    ]
    today_down_wire = deflated_stream_bytes(today_down)
    echoed_down_wire = deflated_stream_bytes(echoed_down)

    # --- Downlink: what the guesser's own socket receives under the ack ------
    acks = [ack_packet(index) for index in range(args.guesses)]
    # The ack shares the guesser's own downlink context with the echoes it also
    # receives, so it is measured interleaved rather than in a stream of its own.
    own_today = [today_down[index] for index in range(args.guesses)]
    own_with_acks: list[bytes] = []
    for index in range(args.guesses):
        own_with_acks.append(own_today[index])
        own_with_acks.append(acks[index])
    own_today_wire = sum(deflated_stream_bytes(own_today))
    own_acks_wire = sum(deflated_stream_bytes(own_with_acks)) - own_today_wire

    print(f"Guess delivery benchmark - {args.players} players, "
          f"{args.guesses} guesses per guesser\n")

    def row(label: str, raw: int, wire: int, per: int) -> None:
        print(f"{label:<38}{raw:>9,}B{wire:>10,}B{wire / per:>11,.1f}B")

    print(f"{'':<38}{'raw':>10}{'wire':>11}{'per guess':>12}")
    print("-" * 71)
    print("uplink, the guesser's own socket")
    row("  today", sum(len(m) for m in today_up), sum(today_up_wire), args.guesses)
    row("  with id + ack request",
        sum(len(m) for m in confirmed_up), sum(confirmed_up_wire), args.guesses)
    up_delta = sum(confirmed_up_wire) - sum(today_up_wire)
    print(f"{'  added':<38}{'':>10}{up_delta:>10,}B{up_delta / args.guesses:>11,.1f}B")

    print("\ndownlink, one other socket in the room")
    n = len(room_echoes)
    row("  today", sum(len(m) for m in today_down), sum(today_down_wire), n)
    row("  echo carries the id", sum(len(m) for m in echoed_down), sum(echoed_down_wire), n)
    echo_delta = sum(echoed_down_wire) - sum(today_down_wire)
    print(f"{'  added':<38}{'':>10}{echo_delta:>10,}B{echo_delta / n:>11,.1f}B")

    print("\ndownlink, the guesser's own socket")
    print(f"{'  ACK packets':<38}{sum(len(a) for a in acks):>9,}B"
          f"{own_acks_wire:>10,}B{own_acks_wire / args.guesses:>11,.1f}B")

    audience = max(0, args.players - 1)
    echo_cost = (echo_delta / n) * audience
    ack_cost = own_acks_wire / args.guesses
    print("\nper guess, whole room:")
    print(f"  echo-matching : {up_delta / args.guesses:>5.1f} B up "
          f"+ {echo_cost:>5.1f} B down ({audience} sockets) = "
          f"{up_delta / args.guesses + echo_cost:>5.1f} B")
    print(f"  ack           : {up_delta / args.guesses:>5.1f} B up "
          f"+ {ack_cost:>5.1f} B down (1 socket)  = "
          f"{up_delta / args.guesses + ack_cost:>5.1f} B")
    print(f"\n  a retry costs one more uplink packet: "
          f"{sum(confirmed_up_wire) / args.guesses:.1f} B, only when one is needed")


if __name__ == "__main__":
    main()
