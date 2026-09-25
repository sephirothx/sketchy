import { ui } from "../content/ui/index.ts";

/**
 * Which build this is: the short git commit SHA (a trailing "*" means the
 * working tree had uncommitted changes at build time) and when it was built.
 *
 * A quiet line at the foot of Player settings, on every section. It used to be
 * pinned to the lobby's bottom-right corner on every visit, over content on a
 * narrow screen, for the one reader in a thousand checking whether a fix had
 * shipped - and that reader knows where Settings is. A bug report carries the
 * SHA on its own (`lib/bugReports.ts`), so nobody has to copy it from here.
 */
export function VersionBadge() {
  return (
    <p
      className="version-badge"
      title={ui.versionBadge.buildDetails({ commitDate: __APP_COMMIT_DATE__, builtAt: __APP_BUILD_TIME__ })}
    >
      {ui.versionBadge.version({ sha: __APP_COMMIT_SHA__, builtAt: __APP_BUILD_TIME__ })}
    </p>
  );
}
