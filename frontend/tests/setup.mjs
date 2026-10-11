/* English, set up before any test imports a module (#1426).

English is a chunk like every other language now, fetched before the app's
first paint rather than bundled into the entry; the tests read `ui` as
modules load and expect English, so it is loaded and put in force here,
once per test file (`--import`). */
import { loadCatalogue, setCatalogue } from "../src/content/ui/index.ts";

await loadCatalogue("en");
setCatalogue("en");
