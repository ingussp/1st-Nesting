# 1st Nesting

**A FreeCAD workbench for arranging parts on sheets and reusable offcuts, with texture matching and coloured SVG reports.**

The workbench is named **1st Nesting**. Its Python modules use the `Nesting1st` prefix
(for example, `Nesting1stGui.py`); Python's normal import syntax cannot use a module
identifier beginning with a digit. The repository URL and installation folder remain
`IP-Nesting` for this rename. See [rename compatibility](docs/RENAME_COMPATIBILITY.md)
for saved-document and preference compatibility.

[User guide with screenshots](docs/USER_GUIDE.md) · [Repository description](docs/REPOSITORY_DESCRIPTION.md) · [MIT licence](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)

1st Nesting connects FreeCAD geometry to the [CLI-nesting engine](https://github.com/ingussp/CLI-nesting). Prepare parts, quantities, rotations and stock in FreeCAD, run a nesting search, then inspect the layout as original FreeCAD geometry or export an SVG report. Texture groups keep manually arranged parts together so their relative positions and grain direction survive nesting.

On first use, the workbench offers to download the latest stable CLI-nesting release for **Windows x64, Linux x64, Linux ARM64 or macOS Universal 2**. An existing Windows executable is also included; it remains available until a successful update. Settings includes **Check for updates**. See [engine installation and updates](docs/ENGINE_UPDATES.md).

## Contents

- [Features](#features)
- [Requirements and installation](#requirements-and-installation)
- [Quick start](#quick-start)
- [Engine updates](#engine-updates)
- [Parts and contours](#parts-and-contours)
- [Sheets and offcuts](#sheets-and-offcuts)
- [Texture direction and matching](#texture-direction-and-matching)
- [Search and settings](#search-and-settings)
- [Results and SVG export](#results-and-svg-export)
- [Job files and saved data](#job-files-and-saved-data)
- [Languages](#languages)
- [Troubleshooting](#troubleshooting)
- [Development and validation](#development-and-validation)
- [Licensing](#licensing)

## Features

- Add selected FreeCAD parts, including solids imported from STEP.
- Import DXF and SVG contours; import several DXF files in one operation.
- Set quantities, allowed rotations and texture direction per part or group.
- Nest on rectangular sheets and irregular DXF offcuts, including selected holes.
- Edit sheet dimensions, contours, quantities and grain direction.
- Arrange texture groups by dragging transparent outlines, with snapping, collision detection and minimum spacing.
- Export curved and concave part perimeters instead of replacing them with bounding boxes.
- Choose Fast or Continuous search, an optional Continuous deadline and CPU settings; optionally use OpenCL.
- Reconstruct results from original geometry, preserving machining details and the displayed top/bottom orientation.
- Add [manual cutting bridges](docs/BRIDGES.md) to join nested parts into one 3D solid or 2D cutting profile, with collision checks and editable mm/inch widths.
- Export a coloured SVG report with part legends, positions, angles, areas and sheet utilisation.
- Use an offline interface in 50 languages, including Latvian.

## Requirements and installation

| Component | Requirement |
| --- | --- |
| FreeCAD | Tested with FreeCAD 1.0 and 1.1 on Windows x64 |
| Python and Qt | FreeCAD's bundled Python, Part module and PySide; no separate pip installation is needed for normal use |
| Nesting engine | Matching CLI-nesting GitHub release, offered on first use; an existing Windows x64 build is included |
| GPU | Optional; OpenCL must be provided by an installed GPU driver |
| File access | The workbench folder must be writable for job files, logs and locks |

### Windows

1. Close FreeCAD before installing or replacing workbench files.
2. Download this repository or clone it into `%APPDATA%\FreeCAD\Mod\IP-Nesting`.
3. Ensure `InitGui.py` is directly inside `IP-Nesting`, without an extra nested archive folder.
4. Start FreeCAD and select **1st Nesting** in the workbench selector.
5. Accept the first-use offer to download the engine for your system, or install later from Settings.
6. Open **Nesting Tool** from its toolbar/menu. The gear button opens settings; settings are also available from the workbench menu.

For a new installation with Git:

```powershell
New-Item -ItemType Directory -Force -Path "$env:APPDATA\FreeCAD\Mod"
git clone https://github.com/ingussp/IP-Nesting.git "$env:APPDATA\FreeCAD\Mod\IP-Nesting"
```

The clone command requires a destination that does not already contain a checkout. Preserve your local changes, job files and results before updating an existing installation. To locate FreeCAD's actual user data folder, run `App.getUserAppDataDir()` in its Python console.

### Linux and macOS

Install the workbench under the `Mod` folder in FreeCAD's user data directory. Accept the first-use offer or use **Settings → Check for updates** to install the matching release. Manual installations can use these repository-relative paths:

| Platform | Path |
| --- | --- |
| Linux x64 | `clinesting/linux-x86_64/clinesting` |
| Linux ARM64 | `clinesting/linux-aarch64/clinesting` |
| macOS Universal 2, preferred | `clinesting/macos-universal2/clinesting` |
| macOS Intel fallback | `clinesting/macos-x86_64/clinesting` |
| macOS Apple Silicon fallback | `clinesting/macos-arm64/clinesting` |

These folders are initially placeholders; the updater fills the matching folder and sets Linux/macOS executable permission. A manually supplied executable must implement the same JSON/job protocol. The workbench does not search PATH for another nesting executable. See [engine documentation](clinesting/README.md).

## Quick start

1. Open or create your parts in FreeCAD. For STEP, use FreeCAD's normal file import/open workflow.
2. Select the desired objects and open Nesting Tool. Selected source objects are added automatically when appropriate; use **Add selected** for further objects.
3. Alternatively, import DXF or SVG parts from the panel.
4. Add stock sheets or import offcuts. Select a sheet and use **Edit** to change it.
5. Enter part quantities, allowed rotations, **Sheet margin** and **Part spacing**.
6. Set **Texture direction** where needed. Use **Match texture** to keep an arranged set of parts together.
7. Choose a search mode and click **Run nesting**. In Continuous mode, use **Cancel** when satisfied; already published valid layouts remain available.
8. Inspect **Nesting_Result**, then click **Export nesting result to SVG** to save a report.

Dimensions can be displayed in millimetres or inches. Geometry and job data use millimetres internally.

## Engine updates

Open Settings and press **Check for updates** in the CLI-nesting row below Batch size.
Checks use the latest stable release; a newer version offers installation, while the
same or an older version leaves the engine untouched. Downloads run in the background
with Cancel, SHA-256/archive/architecture/version checks and rollback on failed replacement.
The engine cannot be replaced during an active nesting job. Original geometry and
saved job files are unaffected by installation. See [the update guide](docs/ENGINE_UPDATES.md).

## Parts and contours

The part table contains numbered rows, quantities, rotation specifications, selection controls, texture direction and custom angles. Texture groups receive their own numbered rows and participate in the same nesting workflow.

Parts are copied to **Nesting_Preview**, where their orientation and arrangement can be inspected. Imported 2D geometry is converted to stable FreeCAD features. Each selected DXF file becomes a separate part row; failed files are reported without discarding successfully imported files.

### Rotation specifications

| Entry | Allowed angles |
| --- | --- |
| `1` | 0° |
| `4` | 0°, 90°, 180°, 270° |
| `(45)` | Every 45° |
| `[0, 180]` | 0° and 180° |

Explicit angle lists are deduplicated and include the 0° starting orientation. Enable both **Texture Direction** and **Custom angle** before using **Set custom angle** to change the displayed orientation. The nesting rotation options are applied relative to the exported orientation.

### Curves, holes and machining

The exporter uses the part's actual XY footprint, including concave boundaries. Curved edges are approximated with line segments using **Contour approximation tolerance**, initially 0.01 mm. Exported coordinates retain six decimal places; the original BREP geometry is saved separately for reconstructing results.

Use **Mark selected part holes** to choose inner contours available for nesting. Blind holes and grooves can be shown as projected machining outlines, but do not become through holes in the nesting polygon. A usable footprint must enclose the actual material: invalid, open or incompatible geometry produces a diagnostic instead of a silent bounding-box substitution.

## Sheets and offcuts

Add rectangular sheets with dimensions and quantities, or import irregular stock from DXF. Adding identical stock increases its available quantity. Use **Edit** for sheet boundaries, holes and grain direction, and **Remove** to delete stock rows.

Stock geometry is exported in its local coordinates. Moving a preview sheet changes its display position without changing its usable boundary. Grain X/Y refers to the sheet's local axes. Sheet holes can use the standard part spacing or a custom hole-to-part clearance.

**Sheet margin** reserves distance from the outer stock boundary. **Part spacing** reserves distance between parts. Their initial values are 5 mm and 6 mm respectively, and fractional values are supported.

## Texture direction and matching

### Texture direction

Enabling **Texture direction** aligns the part in the preview area and shows a direction arrow. Choosing Y rotates the displayed geometry together with the arrow so the arrow remains horizontal on screen. Bulk X/Y changes apply immediately to the selected parts. Disabling texture direction restores the saved ordinary orientation; rotations preserve the displayed top/bottom face.

For a texture group, enabling direction also sets **Rotations** to `[0, 180]`. Nesting then preserves the group's aligned texture axis.

### Creating and editing a group

1. Select at least two part rows with equal quantities.
2. Click **Match texture**, below the part-hole control.
3. Drag parts in the shared workspace. All outlines are transparent, including curved edges and projected machining details from both faces.
4. Select a part and press **Rotate** for a 90° clockwise turn about its bounding-box centre.
5. Click **Save group** when the arrangement is valid.

Use the mouse wheel to zoom and the middle mouse button to pan. Snapping uses an invisible grid and nearby edges/centres. The grid step is one tenth of the shorter bounding-box side of the part with the smallest bounding-box area, rounded to whole millimetres with a 1 mm minimum. This rounding does not round part dimensions or fractional spacing.

Collision detection checks actual outer contours and the path of a drag, prevents overlaps, stops parts at **Part spacing**, and allows sliding along neighbouring parts. A rotation that violates spacing is refused. Save group remains unavailable while the arrangement is invalid.

The saved group becomes an active table row; its member rows become inactive. Select the group or a member and open Match texture again to edit it. **Remove matching** dissolves an existing group and reactivates the members. For a new, unsaved selection it cancels matching. Cancelling the editor leaves the saved preview arrangement untouched.

### Group export and reconstruction

The group is exported as **one part in its displayed arrangement**, with ordinary part metadata. Its perimeter follows the arranged members instead of their bounding box. FreeCAD metadata is stored in the matching session file; the engine input uses the accepted `name` field for the label. Touching contours are combined; separated members are connected by local bridges to form a single enclosing proxy. Concave and curved outer boundaries remain represented, while internal gaps reserved by the group are unavailable to unrelated parts.

The session records each original member and its relative position/angle. A placed group is reconstructed as separate original FreeCAD parts and separate SVG contours. If source geometry changes, reopen and confirm the group; if the required spacing increases beyond its saved gaps, edit the arrangement before nesting.

## Search and settings

### Search modes

| Mode | Behaviour |
| --- | --- |
| Fast (`first`) | Build and export one complete initial layout; deadline and initial-layout budget controls are disabled |
| Continuous | Improve until cancellation or the total time limit; 0 seconds means unlimited |

Only Continuous uses **Time limit (seconds)**. Its total budget includes preparation,
the initial layout and CPU/GPU search. **Continuous round (seconds)** bounds the
initial-layout search and is capped by the remaining total budget. Cancellation
and deadlines are cooperative; an active geometry/GPU call or output can add time.

Saved `timed` preferences migrate to `continuous` while retaining their time limit.
The current engine chooses its own search strategies; the retired strategy selector
and the unsupported `algorithm`/`trials` JSON fields are no longer used.

CPU choices reflect available logical cores, capped at 16. GPU use is optional. Click **Show GPUs** to discover OpenCL devices; discovery is not triggered merely by opening the panel. Select an available device or automatic selection. CPU operation remains available without OpenCL hardware.

### Settings menu

Settings are available from the gear button or the workbench menu, even without an open task panel. Preferences are stored under `BaseApp/Preferences/Mod/IPNesting`.

| Setting | Initial value | Purpose |
| --- | --- | --- |
| Language | English | Live interface language |
| Default rotations | 4 | Rotation count for newly added parts |
| Contour approximation tolerance | 0.01 mm | FreeCAD curve-to-polygon deviation |
| Bitmap resolution | 1 mm/px | Nesting raster pixel size |
| Search step | 1 px | Candidate search step |
| Cache rejected positions | Enabled | Reuse rejected position checks |
| Contact simplification | 0.3 mm | Simplify contours used to propose contact positions; 0 disables it |
| Batch size | 65,536 | GPU batch size, 256–262,144; located below Contact simplification |

Contour approximation, bitmap resolution and contact simplification are separate controls. Contact simplification does not replace the original contours used for occupancy, vector validation or result geometry. Geometric tolerances use millimetres even when sheet dimensions are displayed in inches. Previously saved preferences override the initial values. See [search settings](docs/SEARCH_SETTINGS.md).

## Results and SVG export

Successful snapshots are imported into **Nesting_Result**. Each sheet has a group containing its stock and placed parts. Original geometry and colours are reconstructed from the job snapshot, including machining features and the displayed top/bottom orientation. Continuous updates reuse the result document, and successful display activates the top view and **ViewFitAll**.

**Export nesting result to SVG** exports the latest successfully imported result from the current task panel. Choose a destination file; cancelling the save dialog leaves files untouched. A newly opened panel needs a successful result before export becomes available.

The report includes:

- Stock contours and selected holes, with each placed part in a separate colour.
- Part numbers and a legend containing labels, XY coordinates, rotations and net areas.
- Overall and per-sheet utilisation and waste, used sheet counts, placed/unplaced counts and unplaced part information.
- Job identity and report creation time.

Texture members appear individually. Utilisation uses actual net part areas and net sheet areas, rather than the area of a group's enclosing proxy. Engine-generated remaining offcuts can be conservative around groups because reserved internal gaps are not available for nesting.

SVG is a layout/report export with millimetre geometry and a scaled page presentation. It does not generate CNC toolpaths, tool compensation or G-code.

## Job files and saved data

The following files are created **in the workbench folder**, not beside the platform-specific executable:

| File | Purpose |
| --- | --- |
| `input.json` | Strict CLI part/stock polygons, names, quantities, rotations, margins, search and hardware settings |
| `nesting_session.json` | Original geometry, identities, colours, orientation and texture-member recipes |
| `result.json` | Latest complete engine snapshot |
| `results/resultN.json` | Improving snapshots from Continuous mode |
| `clinesting.log` | Engine diagnostics |
| `.ipnesting-job.lock`, `.clinesting-results.lock` | Exclusive job/result ownership |
| `.clinesting-cancel-*` | Job-specific cancellation marker |

Input, session and result share a job UUID; mismatched results are rejected. Original geometry is frozen at export, so results do not depend on a subsequently changed or closed preview document. Keep the session with its matching result for geometry reconstruction.

A new Continuous job clears the engine's `results/` snapshot directory under its lock. Archive results you want to retain before starting another job. Saving the FreeCAD document preserves document geometry and texture group data; preferences are saved separately, and reopening an FCStd file does not restore every task-panel control or the last in-memory SVG export state.

## Languages

The interface starts in English independently of FreeCAD's language. Choose **Language** in Settings to search by name or language code and switch immediately. All 50 JSON catalogs are bundled in `lng/`; no translation service is called during use. Right-to-left interface handling is included.

User-defined part labels and technical identifiers remain unchanged. Automated checks verify catalog coverage and placeholders; native-speaker terminology corrections are welcome. See [language documentation](docs/LANGUAGES.md).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Workbench is missing | Correct `Mod/IP-Nesting` location, direct `InitGui.py`, then restart FreeCAD |
| Executable not found | Correct platform folder; only Windows x64 is bundled |
| Job files cannot be written | Write access to the workbench folder |
| GPU list is empty | Use Show GPUs and check the installed OpenCL driver; try CPU mode |
| DXF/SVG cannot be used | Closed contours, usable scale, correct import and valid projected geometry |
| A part fails footprint validation | Its XY contour must enclose the solid; inspect disconnected material, non-planar placement or invalid wires |
| Group cannot be saved | Equal quantities, no overlap and at least the configured part spacing |
| Existing group fails after a change | Reopen it after geometry changes or increased spacing and save a valid arrangement |
| Part remains unplaced | Stock size/quantity, margin, holes, spacing, grain and allowed rotations; consider a longer search |
| Result has a different job identity | Do not mix input/session/result files from different runs |
| SVG export is unavailable | Run nesting and successfully import a result in the current panel |

For reproducible problems, include FreeCAD version, operating system, steps, relevant settings and `clinesting.log`. Share geometry or job data only when you are comfortable publishing its contents.

## Development and validation

The workbench is Python code loaded by FreeCAD. The nesting executable is maintained in the separate [CLI-nesting repository](https://github.com/ingussp/CLI-nesting).

| Module or folder | Responsibility |
| --- | --- |
| `InitGui.py` | Workbench registration and commands |
| `Nesting1stGui.py`, `Nesting1stSettings.py`, `Nesting1stLanguages.py` | Main panel, preferences and translations |
| `Nesting1stPreviewDoc.py`, `Nesting1stRelayout.py`, `Nesting1stRotate.py` | Preview geometry, layout and orientation |
| `Nesting1stImport2D.py`, `Nesting1stOffcuts.py`, `Nesting1stAddSheet.py` | Part imports and stock creation |
| `Nesting1stOffcutShowDialog.py`, `Nesting1stPartHoles.py` | Stock editing and selectable holes |
| `Nesting1stGrain*.py` | Texture alignment, group model and manual editor |
| `Nesting1stExport.py`, `Nesting1stRuntime.py` | Polygon export and engine/job protocol |
| `Nesting1stEngine.py`, `Nesting1stEngineUI.py` | Release selection, verified installation, first-use setup and explicit updates |
| `Nesting1stResult.py`, `Nesting1stResultSVG.py` | FreeCAD reconstruction and SVG reports |
| `Nesting1stAsync.py`, `Nesting1stGpu.py`, `Nesting1stWaitDialog.py` | Job execution, device discovery and progress/cancellation |
| `clinesting/` | Platform binaries, build manifest and dependency licence texts |
| `lng/`, `docs/`, `tests/` | Language catalogs, focused documentation and regression checks |

Run ordinary Python tests from the repository root:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Geometry and GUI checks need **FreeCAD's bundled Python**, including its Part and Qt modules. Example for a FreeCAD 1.1 user installation:

```powershell
& "$env:LOCALAPPDATA\Programs\FreeCAD 1.1\bin\python.exe" tests/freecad_geometry_regression.py
& "$env:LOCALAPPDATA\Programs\FreeCAD 1.1\bin\python.exe" tests/freecad_workbench_integration.py
```

Other native checks are `freecad_grain_controls.py`, `freecad_grain_matching.py`, `freecad_result_svg.py`, `freecad_progress_and_view.py`, `freecad_dxf_batch_import.py`, `freecad_search_settings.py` and `gui_language_smoke.py` in `tests/`. GUI scripts use offscreen Qt where appropriate; integration checks use disposable job folders. Adjust the Python path to your FreeCAD installation. The matching test accepts `CLINESTING_EXE` for a compatible test engine and `GRAIN_MATCH_SCREENSHOT` for a preview screenshot destination.

Report bugs or suggest improvements through [GitHub issues](https://github.com/ingussp/IP-Nesting/issues). Include a minimal example and expected versus actual behaviour. Preserve translation placeholders, millimetre job coordinates and input/session/result identity checks when contributing.

## Licensing

Original 1st Nesting workbench code, documentation and original assets are released under the [MIT licence](LICENSE). It permits free use, modification and redistribution, including commercial use, subject to retaining its notice; see the [standard MIT licence](https://opensource.org/license/mit).

Separately sourced components retain their own terms. The bundled engine uses Clipper2 (Boost Software License 1.0), nlohmann/json (MIT) and OpenCL-Headers (Apache 2.0); their complete texts are preserved in `clinesting/licenses/`.

The pinned CLI-nesting source and binary bundle do **not currently declare a separate licence for the engine's own code**. The 1st Nesting MIT grant does not assign a licence to that separate component. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for exact scope, source commit and dependency notices. FreeCAD, Qt and installed drivers have their own licences.
