# Licensing scope and third-party notices

## Original 1st Nesting work

The root [MIT licence](LICENSE) covers original 1st Nesting workbench code, documentation and original assets. Copyright (c) 2026 Inguss (ingussp) and 1st Nesting contributors.

Separately sourced software retains its own terms. The root licence does not replace dependency licences or assign a licence to a separately sourced executable.

## Bundled CLI-nesting executable

| Item | Identification |
| --- | --- |
| Source repository | [ingussp/CLI-nesting](https://github.com/ingussp/CLI-nesting) |
| Source commit | [cb3579d52fa5a1ae82c687198eca92eaa7d8515a](https://github.com/ingussp/CLI-nesting/tree/cb3579d52fa5a1ae82c687198eca92eaa7d8515a) |
| Included binary | `clinesting/windows-x86_64/clinesting.exe` |
| Build metadata | [clinesting/manifest.json](clinesting/manifest.json) |
| Protocol | `workbench-job-v1`; see [engine documentation](clinesting/README.md) |

At the pinned source commit, CLI-nesting has no standalone licence declaration for its own engine code. The bundled files likewise provide dependency licence texts, but no separate engine licence. Its [upstream licensing section](https://github.com/ingussp/CLI-nesting/blob/cb3579d52fa5a1ae82c687198eca92eaa7d8515a/README.md#dependencies-and-licenses) describes third-party dependencies.

Those dependency licences do not constitute a licence grant for the engine's original code. The 1st Nesting MIT licence therefore applies to the workbench's original work, not to this separate engine component. A licence declaration from the engine's copyright holder is still needed to make its own distribution terms explicit.

## Engine dependencies

Versions below are recorded in the pinned engine source documentation. Their existing complete licence texts are retained unchanged in this repository.

| Component | Version | Licence | Included full text |
| --- | --- | --- | --- |
| [Clipper2](https://github.com/AngusJohnson/Clipper2) | 1.5.4 | Boost Software License 1.0 | [Clipper2.txt](clinesting/licenses/Clipper2.txt) |
| [nlohmann/json](https://github.com/nlohmann/json) | 3.11.3 | MIT | [nlohmann-json.txt](clinesting/licenses/nlohmann-json.txt) |
| [OpenCL-Headers](https://github.com/KhronosGroup/OpenCL-Headers) | v2024.10.24 | Apache License 2.0 | [OpenCL-Headers.txt](clinesting/licenses/OpenCL-Headers.txt) |

Retain applicable copyright, attribution and licence notices when redistributing these components. Refer to the full texts for their terms.

## Separately installed software

FreeCAD, its Python/Qt/PySide/Open CASCADE components, and system GPU/OpenCL drivers are installed separately and retain their respective licences. This repository does not relicense them under MIT.

## User designs and generated files

The workbench licence does not claim ownership of user-provided FCStd, STEP, DXF or SVG designs, or grant rights in designs contained in generated layouts and reports. Rights in those designs remain with their respective owners.
