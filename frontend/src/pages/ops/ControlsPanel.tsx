import { useCallback, useEffect, useState } from "react";

import { Chip } from "../../components/ui/Chip";
import { ApiError } from "../../lib/api";
import {
  closeRoom,
  endTurn,
  initiateShutdown,
  kickPlayer,
  readLiveRooms,
  readMaintenance,
  setMaintenance,
  setPlayerRole,
  type LiveRoom,
  type MaintenanceState,
} from "../../lib/adminControls";

/** Commands, kept apart from the settings on purpose.

A tunable has a default, a range and a way back. Pausing the server, closing
somebody's room and granting a role have none of those, and an irreversible
button in a row of sliders is a button pressed by accident. */
export function ControlsPanel() {
  const [maintenance, setMaintenanceState] = useState<MaintenanceState | null>(null);
  const [rooms, setRooms] = useState<LiveRoom[]>([]);
  const [reason, setReason] = useState("");
  const [shutdownReason, setShutdownReason] = useState("");
  const [drainSeconds, setDrainSeconds] = useState("");
  const [confirmingShutdown, setConfirmingShutdown] = useState(false);
  const [roleUserId, setRoleUserId] = useState("");
  const [roleReason, setRoleReason] = useState("");
  const [role, setRole] = useState<"user" | "moderator">("moderator");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  // Which room's seats are open. Collapsed by default: the table is for
  // finding a room, and a list of every player in every room would bury it.
  const [openSeats, setOpenSeats] = useState<string | null>(null);

  const fail = useCallback((failure: unknown, fallback: string) => {
    setError(failure instanceof ApiError ? failure.message : fallback);
    setDone(null);
  }, []);

  const load = useCallback(() => {
    void readMaintenance()
      .then(setMaintenanceState)
      .catch((failure) => fail(failure, "Could not read the maintenance state."));
    void readLiveRooms()
      .then((result) => setRooms(result.rooms))
      .catch((failure) => fail(failure, "Could not list the live rooms."));
  }, [fail]);

  useEffect(load, [load]);

  function run(action: Promise<unknown>, message: string) {
    setBusy(true);
    setError(null);
    void action
      .then(() => {
        setDone(message);
        load();
      })
      .catch((failure) => fail(failure, "That command was refused."))
      .finally(() => {
        setBusy(false);
        setConfirming(null);
      });
  }

  const paused = maintenance?.paused ?? false;

  return (
    <div className="ops-controls">
      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
      {done && !error && (
        <p className="ops-saved" role="status">
          {done}
        </p>
      )}

      <section className="ops-card" aria-label="Maintenance">
        <div className="ops-card-head">
          <div>
            <h2>Maintenance</h2>
            <p className="ops-card-sub">
              Pausing refuses new rooms, game starts and restart votes. Games
              already running carry on and finish normally, and the server keeps
              reporting itself ready — this is not a shutdown.
            </p>
          </div>
          <Chip kind={paused ? "warm" : "success"}>
            {paused ? "Paused" : "Accepting rooms"}
          </Chip>
        </div>
        {maintenance?.draining && (
          <p className="ops-empty">
            A shutdown drain is already running; the pause control is not
            available while it finishes.
          </p>
        )}
        <div className="ops-filters">
          <label htmlFor="ops-pause-reason">Reason</label>
          <input
            id="ops-pause-reason"
            value={reason}
            placeholder="database migration"
            onChange={(change) => setReason(change.target.value)}
          />
          <button
            type="button"
            className={paused ? "btn btn-primary btn-compact" : "btn btn-secondary btn-compact"}
            disabled={busy || maintenance?.draining}
            onClick={() =>
              run(
                setMaintenance(!paused, reason),
                paused ? "New rooms are open again." : "New rooms are paused.",
              )
            }
          >
            {paused ? "Resume" : "Pause new rooms"}
          </button>
        </div>
      </section>

      <section className="ops-card" aria-label="Live rooms">
        <div className="ops-card-head">
          <div>
            <h2>Live rooms</h2>
            <p className="ops-card-sub">
              {rooms.length} held by this process. Prompts, chat and canvases are
              not shown here — reading a room's content is what the moderation
              queue is for, with the evidence trail that goes with it.
            </p>
          </div>
          <button type="button" className="btn btn-ghost btn-compact" onClick={load}>
            Refresh
          </button>
        </div>
        {rooms.length === 0 && <p className="ops-empty">No rooms are open.</p>}
        {rooms.length > 0 && (
          <div className="ops-table-scroll">
            <table className="ops-table">
              <thead>
                <tr>
                  <th scope="col">Room</th>
                  <th scope="col">Code</th>
                  <th scope="col">State</th>
                  <th scope="col">Players</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rooms.map((room) => (
                  <tr key={room.id}>
                    <td>{room.name}</td>
                    <td className="ops-identifier">{room.code}</td>
                    <td>
                      {room.state}
                      {room.phase && ` · ${room.phase}`}
                    </td>
                    <td className="ops-number">
                      <button
                        type="button"
                        className="auth-link"
                        aria-expanded={openSeats === room.id}
                        onClick={() =>
                          setOpenSeats((current) =>
                            current === room.id ? null : room.id,
                          )
                        }
                      >
                        {room.players}
                        {room.spectators > 0 && ` +${room.spectators}`}
                      </button>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-compact"
                        disabled={busy || room.phase !== "drawing"}
                        onClick={() =>
                          run(endTurn(room.id), "The turn was ended.")
                        }
                      >
                        End turn
                      </button>
                      {confirming === room.id ? (
                        <>
                          <button
                            type="button"
                            className="btn btn-danger-ghost btn-compact"
                            disabled={busy}
                            onClick={() =>
                              run(closeRoom(room.id), "The room was closed.")
                            }
                          >
                            Confirm close
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-compact"
                            onClick={() => setConfirming(null)}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-ghost btn-compact"
                          disabled={busy}
                          onClick={() => setConfirming(room.id)}
                        >
                          Close room
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {rooms
                  .filter((room) => room.id === openSeats)
                  .map((room) => (
                    <tr key={`${room.id}-seats`} className="ops-seats-row">
                      <td colSpan={5}>
                        {room.seats.length === 0 && (
                          <span className="ops-empty">Nobody is seated.</span>
                        )}
                        <ul className="ops-seats">
                          {room.seats.map((seat) => (
                            <li key={seat.id}>
                              <span>{seat.nickname}</span>
                              {seat.isSpectator && (
                                <Chip kind="neutral">Watching</Chip>
                              )}
                              {!seat.connected && (
                                <Chip kind="neutral">Disconnected</Chip>
                              )}
                              {confirming === seat.id ? (
                                <>
                                  <button
                                    type="button"
                                    className="btn btn-danger-ghost btn-compact"
                                    disabled={busy}
                                    onClick={() =>
                                      run(
                                        kickPlayer(room.id, seat.id),
                                        `${seat.nickname} was removed.`,
                                      )
                                    }
                                  >
                                    Confirm kick
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn-ghost btn-compact"
                                    onClick={() => setConfirming(null)}
                                  >
                                    Cancel
                                  </button>
                                </>
                              ) : (
                                <button
                                  type="button"
                                  className="btn btn-ghost btn-compact"
                                  disabled={busy}
                                  onClick={() => setConfirming(seat.id)}
                                >
                                  Kick
                                </button>
                              )}
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="ops-card ops-danger" aria-label="Shutdown">
        <div className="ops-card-head">
          <div>
            <h2>Shut down this server</h2>
            <p className="ops-card-sub">
              Stops accepting new work, gives games already running a bounded
              window to finish, records anything that outlives it as abandoned,
              and then exits. Live rooms are not saved — they are process-owned
              and do not survive a restart.
            </p>
          </div>
          <Chip kind="warm">Irreversible from here</Chip>
        </div>
        <p className="ops-empty">
          <strong>Nothing here starts it again.</strong> Under a supervisor —
          systemd, a container restart policy — this is a restart. Without one
          it is a stop, and bringing Sketchy back needs access to the host.
        </p>
        <div className="ops-filters">
          <label htmlFor="ops-drain">Drain seconds</label>
          <input
            id="ops-drain"
            type="number"
            min={0}
            max={300}
            className="ops-drain-input"
            value={drainSeconds}
            placeholder={String(maintenance?.drainSeconds ?? 30)}
            onChange={(change) => setDrainSeconds(change.target.value)}
          />
          <label htmlFor="ops-shutdown-reason">Reason</label>
          <input
            id="ops-shutdown-reason"
            value={shutdownReason}
            placeholder="deploying 1.4.0"
            onChange={(change) => setShutdownReason(change.target.value)}
          />
          {confirmingShutdown ? (
            <>
              <button
                type="button"
                className="btn btn-danger-ghost btn-compact"
                disabled={busy}
                onClick={() =>
                  run(
                    initiateShutdown(
                      shutdownReason.trim(),
                      drainSeconds.trim() === ""
                        ? undefined
                        : Number(drainSeconds),
                    ),
                    "Draining. The server is stopping.",
                  )
                }
              >
                Confirm shutdown
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-compact"
                onClick={() => setConfirmingShutdown(false)}
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              disabled={
                busy
                || maintenance?.draining
                || shutdownReason.trim().length < 3
              }
              onClick={() => setConfirmingShutdown(true)}
            >
              Initiate shutdown
            </button>
          )}
        </div>
      </section>

      <section className="ops-card" aria-label="Roles">
        <div className="ops-card-head">
          <div>
            <h2>Moderator role</h2>
            <p className="ops-card-sub">
              Grant or revoke moderation for a registered account. Administrators
              are created only by the guarded command on the server, so one
              compromised session here cannot make more of them.
            </p>
          </div>
        </div>
        <div className="ops-filters">
          <label htmlFor="ops-role-user">Account id</label>
          <input
            id="ops-role-user"
            value={roleUserId}
            placeholder="00000000-0000-0000-0000-000000000000"
            onChange={(change) => setRoleUserId(change.target.value)}
          />
          <label htmlFor="ops-role">Role</label>
          <select
            id="ops-role"
            className="ops-select"
            value={role}
            onChange={(change) =>
              setRole(change.target.value === "user" ? "user" : "moderator")
            }
          >
            <option value="moderator">moderator</option>
            <option value="user">user</option>
          </select>
          <label htmlFor="ops-role-reason">Reason</label>
          <input
            id="ops-role-reason"
            value={roleReason}
            placeholder="joining the safety rota"
            onChange={(change) => setRoleReason(change.target.value)}
          />
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            disabled={busy || roleUserId.trim() === "" || roleReason.trim().length < 3}
            onClick={() =>
              run(
                setPlayerRole(roleUserId.trim(), role, roleReason.trim()),
                `That account is now a ${role}.`,
              )
            }
          >
            Set role
          </button>
        </div>
      </section>
    </div>
  );
}
