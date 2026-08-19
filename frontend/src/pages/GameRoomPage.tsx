import { useParams } from "react-router-dom";
import { ActiveGameRoom } from "../components/ActiveGameRoom";
import { InviteEntryPage } from "../components/InviteEntryPage";
import { useGameStore } from "../store/gameStore";

export function GameRoomPage() {
  const { code } = useParams<{ code: string }>();
  const playerId = useGameStore((state) => state.playerId);
  const isExitingRoom = useGameStore((state) => state.isExitingRoom);
  const activeRoomId = useGameStore((state) => state.roomId);
  const activeRoomCode = useGameStore((state) => state.code);
  const normalizedCode = code?.trim().toUpperCase() ?? "";

  // A credential stored for another room must never activate this route.
  const hasActiveSession = Boolean(
    playerId && activeRoomId && activeRoomCode?.toUpperCase() === normalizedCode,
  );

  // On the way out the session is already cleared but the route has not
  // changed yet. Rendering the invite screen for that one frame would ask the
  // server to resume a seat we just gave up.
  if (isExitingRoom) return null;

  if (!hasActiveSession) {
    return <InviteEntryPage key={normalizedCode} code={normalizedCode} />;
  }
  return <ActiveGameRoom code={normalizedCode} />;
}
