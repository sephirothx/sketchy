/** When a room is drawn as the phone's fixed shell - status band, stage, dock,
    or sideways the rail, the canvas and the feed column - rather than the
    desktop's three columns: at most 900px wide, or at most 520px tall at any
    width.

    The second half is a large phone held sideways (915 x 412, 926 x 428,
    932 x 430, 956 x 440) and a short desktop window. Above 900px those used to
    get the desktop DOM while the phone's landscape stylesheet, which has no
    upper width, laid itself over it: the empty dock took a grid track, the
    stage fell into the chat's column, and the canvas came out 0 x 0 for the
    drawer and the guessers alike (#1261). At 520px tall the desktop room
    cannot be pinned anyway (R-UX-01), and three columns of a scrolling page
    left a canvas of about 350px, where the phone's landscape layout gives the
    drawing the whole height.

    Past 900px wide a viewport 520px tall is necessarily landscape, so no
    orientation test is needed. The room's stylesheets say the same thing as
    `@media (max-width: 900px), (max-height: 520px)` and its desktop side as
    `(min-width: 901px) and (min-height: 521px)`; a media query cannot read
    this constant, so `stylesheetScales.test.mjs` holds them to it. */
// Not copy: a media query.
export const PHONE_ROOM_QUERY = "(max-width: 900px), (max-height: 520px)";
