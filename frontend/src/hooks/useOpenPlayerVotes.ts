import { useMemo } from "react";
import { openPlayerVotes, type OpenPlayerVote } from "../lib/playerVotes";
import { useGameStore } from "../store/gameStore";

/** The kick and AFK votes open in the room, as this seat sees them (#1422).

Subscribed through a string, so a component reading them renders again when
a vote opens, moves or closes - not on every score and connection change the
players list carries, which would put the votes' readers (the room bar, the
Room menu) on the path of every guess (R-ENG-16). */
export function useOpenPlayerVotes(): OpenPlayerVote[] {
  const signature = useGameStore((state) =>
    JSON.stringify(openPlayerVotes(state.players, state.moderation, state.playerId)),
  );
  return useMemo(() => JSON.parse(signature) as OpenPlayerVote[], [signature]);
}
