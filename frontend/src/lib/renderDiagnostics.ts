export type RenderRegion =
  | "activeGameRoom"
  | "roomShell"
  | "gameplay"
  | "canvas"
  | "toolbar"
  | "chat"
  | "players";

interface RenderDiagnostics {
  counts: Partial<Record<RenderRegion, number>>;
}

type DiagnosticWindow = Window & {
  __SKETCHY_RENDER_DIAGNOSTICS__?: RenderDiagnostics;
};

const enabled = import.meta.env.VITE_RENDER_DIAGNOSTICS === "true";

export function recordRender(region: RenderRegion) {
  if (!enabled) return;
  const diagnosticWindow = window as DiagnosticWindow;
  const diagnostics = diagnosticWindow.__SKETCHY_RENDER_DIAGNOSTICS__ ??= {
    counts: {},
  };
  diagnostics.counts[region] = (diagnostics.counts[region] ?? 0) + 1;
}
