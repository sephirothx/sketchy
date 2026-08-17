import { useParams } from "react-router-dom";
import { ActiveGameRoom } from "../components/ActiveGameRoom";
import { ConfettiCanvas } from "../components/ConfettiCanvas";
import { InviteEntryPage } from "../components/InviteEntryPage";
import { useGameStore } from "../store/gameStore";

export function GameRoomPage() {
  const { code } = useParams<{ code: string }>();
  const playerId = useGameStore((state) => state.playerId);
  const activeRoomId = useGameStore((state) => state.roomId);
  const activeRoomCode = useGameStore((state) => state.code);
  const normalizedCode = code?.trim().toUpperCase() ?? "";

  // A credential stored for another room must never activate this route.
  const hasActiveSession = Boolean(
    playerId && activeRoomId && activeRoomCode?.toUpperCase() === normalizedCode,
  );

  return (
    <>
      {hasActiveSession ? (
        <ActiveGameRoom code={normalizedCode} />
      ) : (
        <InviteEntryPage key={normalizedCode} code={normalizedCode} />
      )}
      <ConfettiCanvas />
    </>
  );
}
