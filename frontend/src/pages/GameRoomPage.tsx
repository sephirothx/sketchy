import { useNavigate, useParams } from "react-router-dom";
import { ActiveGameRoom } from "../components/ActiveGameRoom";
import { CrashBoundary } from "../components/CrashBoundary";
import { InviteEntryPage } from "../components/InviteEntryPage";
import { emitTransient } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import { CrashPage } from "./CrashPage";

export function GameRoomPage() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const playerId = useGameStore((state) => state.playerId);
  const isExitingRoom = useGameStore((state) => state.isExitingRoom);
  const activeRoomId = useGameStore((state) => state.roomId);
  const activeRoomCode = useGameStore((state) => state.code);
  const clearSession = useGameStore((state) => state.clearSession);
  const setExitingRoom = useGameStore((state) => state.setExitingRoom);
  const reset = useGameStore((state) => state.reset);
  const normalizedCode = code?.trim().toUpperCase() ?? "";

  // A credential stored for another room must never activate this route.
  const hasActiveSession = Boolean(
    playerId && activeRoomId && activeRoomCode?.toUpperCase() === normalizedCode,
  );

  // The clean leave from ActiveGameRoom.performLeave, without its confirmation:
  // there is no board left to confirm over. The seat has to be released here
  // because the socket is a module singleton that unmounting the crashed room
  // never touched - without `leave_room` the seat would stay live in a room
  // nobody is looking at. Only the game store is reset: it is the one piece of
  // state the crashed tree was reading, and the player's settings were not.
  function leaveAfterCrash() {
    setExitingRoom(true);
    clearSession();
    emitTransient("leave_room");
    reset();
    navigate("/");
  }

  // On the way out the session is already cleared but the route has not
  // changed yet. Rendering the invite screen for that one frame would ask the
  // server to reconnect a seat we just gave up.
  if (isExitingRoom) return null;

  if (!hasActiveSession) {
    return <InviteEntryPage key={normalizedCode} code={normalizedCode} />;
  }
  // Keyed on the code so a crash in one room is not carried into the next.
  // Reload keeps the seat: the socket drops, the server holds the seat for its
  // disconnect grace, and useRoomSessionReconnect re-seats on load.
  return (
    <CrashBoundary
      key={normalizedCode}
      scope="room"
      renderFallback={({ error, componentStack }) => (
        <CrashPage
          scope="room"
          error={error}
          componentStack={componentStack}
          onReload={() => window.location.reload()}
          onBackToLobby={leaveAfterCrash}
        />
      )}
    >
      <ActiveGameRoom code={normalizedCode} />
    </CrashBoundary>
  );
}
