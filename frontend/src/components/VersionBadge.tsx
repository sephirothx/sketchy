// Small, unobtrusive build indicator - shows the short git commit SHA (and
// commit date) the current build was produced from. Useful for confirming
// whether a fix has actually been deployed, without needing a manually
// maintained semantic version that could go stale. A trailing "*" means the
// working tree had uncommitted changes at build time, so the build isn't an
// exact match for that commit.
export function VersionBadge() {
  return (
    <div className="version-badge" title={`Build date: ${__APP_COMMIT_DATE__}`}>
      {__APP_COMMIT_SHA__}
    </div>
  );
}
