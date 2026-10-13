# Engine installation and updates

1st Nesting can download the latest stable CLI-nesting release from
[ingussp/CLI-nesting releases](https://github.com/ingussp/CLI-nesting/releases).
The initial release is `v1.0`.

## First use

Selecting the 1st Nesting workbench for the first time offers to install the
nesting engine for the detected system. Opening Nesting Tool directly also
triggers this offer. Accepting it starts the check and download; declining it
leaves the existing installation untouched and prevents repeated startup prompts
for that platform. You can install later from Settings.

No network request is made before accepting the first-use offer. Opening
Settings does not contact GitHub. There are no scheduled background update checks.

## Check for updates

Open Settings and press **Check for updates** in the **CLI-nesting** row below
Batch size. The latest stable GitHub release is compared with the installed
version. A newer release, or an unversioned/missing executable, offers installation.
The same or an older release does not replace a newer local engine.

Checks and downloads run in a worker thread. The progress window has **Cancel**;
cancelling leaves the installed executable unchanged. Failed network, checksum,
archive or version checks likewise preserve it. A successful installation is
available for the next nesting run without restarting FreeCAD.

## Platform selection

| System | Release asset | Installed executable |
| --- | --- | --- |
| Windows x64 | `clinesting-windows-x86_64.tar.gz` | `clinesting/windows-x86_64/clinesting.exe` |
| Linux x64 | `clinesting-linux-x86_64.tar.gz` | `clinesting/linux-x86_64/clinesting` |
| Linux ARM64 | `clinesting-linux-aarch64.tar.gz` | `clinesting/linux-aarch64/clinesting` |
| macOS Intel or Apple Silicon | `clinesting-macos-universal2.tar.gz` | `clinesting/macos-universal2/clinesting` |

Windows ARM64 and 32-bit systems have no matching asset in this release. The
updater reports unsupported systems rather than installing another architecture.
Linux/macOS executable permission is set during preparation. Existing macOS
architecture-specific fallback binaries remain recognised for version checks.

## Verification and installation

The updater uses the public GitHub latest-release API and its asset size/SHA-256
digest. It accepts the matching asset from the CLI-nesting repository and HTTPS
GitHub asset delivery. Archives are bounded in size, and traversal paths, links,
duplicate members and incompatible executable headers are rejected.

The verified executable is checked with `-v` before installation; its version
must match the release tag. The engine and supplied licence files are staged
inside the workbench's `clinesting/` folder. Existing unrelated files are retained.
Replacement uses atomic file moves and restores changed files if installation
fails. It also detects an engine changed manually while downloading.

The workbench's job lock prevents replacing the engine during a nesting job.
Another updater for the same workbench is prevented by a separate update lock.
Finish the active job and press Check for updates again to retry.

Each managed platform folder contains `installation.json`, recording the tag,
version, executable SHA-256, asset URL and archive SHA-256. This receipt describes
the downloaded engine. The root `clinesting/manifest.json` continues to describe
the original bundled build. A valid receipt avoids launching a version process
on subsequent checks; modified binaries are probed again. Receipt files, update
locks, staged downloads and downloaded per-platform licences are ignored by Git.

## Troubleshooting

- Internet access to `api.github.com`, `github.com` and GitHub's HTTPS asset host
  is required for checks/downloads. Existing engines can run offline.
- GitHub's public API rate limits, proxy configuration or TLS failures can prevent
  a check. Retry later or install the matching release manually.
- The workbench folder must be writable, as for normal job files. A read-only
  system installation needs a user-writable workbench location.
- If the executable is in use or replacement is denied, close the active process
  and retry. The previous engine is retained when installation fails.
- Release tags must have numeric versions, such as `v1.0` or `v1.2.3`, with a
  correctly named asset and GitHub SHA-256 digest for each supported platform.

## Validation

Ordinary tests in `tests/test_engine.py` cover platform/version matching,
corrupted downloads, invalid archives, cancellation and replacement rollback.
Run `tests/freecad_engine_updates.py` with FreeCAD's bundled Python for actual Qt
first-use prompts, explicit settings actions, worker responsiveness, cancellation
and active-job locking. Network responses are faked in these regression tests.

The real v1.0 Windows asset has additionally been downloaded, verified,
installed in an isolated workbench copy and used for a nesting job. Linux/macOS
asset formats can be checked on Windows, but execution tests require those systems.
