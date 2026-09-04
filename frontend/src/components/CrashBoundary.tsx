import { Component, type ErrorInfo, type ReactNode } from "react";
import { recordRenderCrash } from "../lib/clientErrorLog";
import type { CrashScope } from "../lib/crashReport";

/** What a boundary knows about the crash it caught. The component stack
    arrives a beat after the error - React commits the fallback first and calls
    `componentDidCatch` after - so it starts null and the fallback re-renders
    once it is known. */
export interface CaughtCrash {
  error: unknown;
  componentStack: string | null;
}

interface Props {
  scope: CrashScope;
  renderFallback: (crash: CaughtCrash) => ReactNode;
  children: ReactNode;
}

interface State {
  crashed: boolean;
  error: unknown;
  componentStack: string | null;
}

/** Catches a render error and shows a fallback instead of a blank page.
 *
 * A class, because React has no hook for this. Two of them exist: one around
 * `<App>` in `main.tsx`, outside the router and every provider, so nothing that
 * can crash sits above it; one around the live room in `GameRoomPage`, inside
 * all of them, so its fallback can leave the room cleanly (R-UX-06).
 *
 * The fallback must be dependency-light. A throw inside it is caught by nothing
 * and is the blank page this exists to remove.
 */
export class CrashBoundary extends Component<Props, State> {
  state: State = { crashed: false, error: null, componentStack: null };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { crashed: true, error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    const componentStack = info.componentStack ?? "";
    recordRenderCrash(this.props.scope, error, componentStack);
    this.setState({ componentStack });
  }

  render(): ReactNode {
    if (!this.state.crashed) return this.props.children;
    return this.props.renderFallback({
      error: this.state.error,
      componentStack: this.state.componentStack,
    });
  }
}
