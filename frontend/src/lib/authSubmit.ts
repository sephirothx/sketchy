import type { AuthUser } from "../store/authStore";

/** Which of the two things the one dialog is doing. */
export type AuthMode = "claim" | "login";

export interface AuthCredentials {
  username: string;
  password: string;
  email?: string;
  code?: string;
}

/** Route the dialog's one object to the two functions behind it.
 *
 * `login` takes `(username, password, code)` and `register` takes
 * `(username, password, email)` — the same arity in a different order, so
 * handing one to a caller expecting the other type-checks and silently drops
 * a field. That is exactly what happened to the second factor: every dialog
 * passed `login` positionally, the code went into the parameter `register`
 * uses for an email, and a staff account could not sign in from anywhere.
 * Written once so there is one place for it to be right. */
export function authSubmitter(
  mode: AuthMode,
  login: (username: string, password: string, code?: string) => Promise<AuthUser>,
  register: (username: string, password: string, email?: string) => Promise<AuthUser>,
): (credentials: AuthCredentials) => Promise<AuthUser> {
  return ({ username, password, email, code }) =>
    mode === "login"
      ? login(username, password, code)
      : register(username, password, email);
}
