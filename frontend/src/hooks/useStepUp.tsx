import { useCallback, useState } from "react";

import { StepUpRequiredError } from "../lib/api";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import { StepUpDialog } from "../components/StepUpDialog";

/**
 * What `guard` resolves with when the person dismissed the prompt instead of
 * proving themselves: the action never ran, so there is nothing to announce.
 *
 * A symbol rather than `undefined`, which several of these actions legitimately
 * resolve to — `setPlayerRole(...).then(() => {…})` among them — so using that
 * as the sentinel silently swallowed their success.
 */
export const STEP_UP_ABANDONED = Symbol("step-up abandoned");

/**
 * Runs a staff action, and asks for the second factor if the server wants it.
 *
 * R-AUTH-21 refuses a destructive action whose session has not proved itself
 * in the last fifteen minutes, and says so with a header rather than a status
 * alone. This turns that refusal into the one thing a moderator can do about
 * it: a prompt, and then the action they asked for, run again.
 *
 * The action is taken as a function rather than as a promise precisely so it
 * can be run twice. Nothing is replayed behind anybody's back - the retry is
 * the same call the person just made, and only after they have typed a code.
 */
export function useStepUp() {
  const [pending, setPending] = useState<{
    reason: string;
    retry: () => void;
    abandon: () => void;
  } | null>(null);

  const guard = useCallback(
    async <T,>(action: () => Promise<T>): Promise<T | typeof STEP_UP_ABANDONED> => {
      try {
        return await action();
      } catch (problem) {
        if (!(problem instanceof StepUpRequiredError)) throw problem;
        return await new Promise<T | typeof STEP_UP_ABANDONED>((resolve, reject) => {
          setPending({
            reason: refusalText(problem, ui.stepUpDialog.confirmYou),
            retry: () => {
              setPending(null);
              action().then(resolve, reject);
            },
            // Settled rather than dropped: a caller awaiting this would
            // otherwise be left holding a promise that never resolves, with
            // its spinner turning, because somebody pressed Cancel.
            abandon: () => {
              setPending(null);
              resolve(STEP_UP_ABANDONED);
            },
          });
        });
      }
    },
    [],
  );

  const dialog = pending ? (
    <StepUpDialog
      reason={pending.reason}
      onProved={pending.retry}
      onCancel={pending.abandon}
    />
  ) : null;

  return { guard, dialog };
}
