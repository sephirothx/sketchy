import { lazy, Suspense, type ComponentProps } from "react";

import type { ReportedDrawing } from "./ReportedDrawing";
import { ui } from "../content/ui/index.ts";

type Props = ComponentProps<typeof ReportedDrawing>;

/** The frame a reported drawing sits in, without the drawing: what shows
while its chunk arrives, and for good if it cannot be had. The caption is
the notice's own words about the drawing, so it stays either way. */
function DrawingFrame({ caption, className, testId, failed }: Props & { failed?: boolean }) {
  return (
    <figure className={`reported-drawing${className ? ` ${className}` : ""}`} data-testid={testId}>
      <p className="reported-drawing-status" role={failed ? "alert" : "status"}>
        {failed ? ui.reportedDrawing.drawingCouldNotBeLoaded : ui.reportedDrawing.loadingTheDrawing}
      </p>
      {caption && <figcaption className="reported-drawing-caption">{caption}</figcaption>}
    </figure>
  );
}

// The picture pulls the whole canvas renderer, which the first-load chunk has
// no room for (#1257), and the suspension and warning notices that show it
// are in that chunk: fetched when a notice shows a drawing. A chunk that
// cannot be fetched is caught here rather than thrown to the crash page;
// `lazy` keeps what this returns, so the frame says so for the page's life.
const Picture = lazy(async () => {
  try {
    const { ReportedDrawing: Loaded } = await import("./ReportedDrawing");
    return { default: Loaded };
  } catch {
    return { default: (props: Props) => <DrawingFrame {...props} failed /> };
  }
});

/** `ReportedDrawing`, fetched as its own chunk when first shown. */
export function LazyReportedDrawing(props: Props) {
  return (
    <Suspense fallback={<DrawingFrame {...props} />}>
      <Picture {...props} />
    </Suspense>
  );
}
