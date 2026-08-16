export function GameAnnouncer({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true" data-testid="game-announcer">
      {message}
    </div>
  );
}
