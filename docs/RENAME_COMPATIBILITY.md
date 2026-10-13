# 1st Nesting rename compatibility

The visible product name is **1st Nesting**. The workbench class is
`Nesting1stWorkbench`; its commands are `Nesting1st_RunNesting` and
`Nesting1st_Settings`. All 28 former workbench modules use the `Nesting1st`
prefix, including `Nesting1stGui.py`, `Nesting1stGpu.py` and
`Nesting1stLanguages.py`. FreeCAD's entry file remains `InitGui.py`.

Restart FreeCAD after updating. Already loaded Python modules and workbench
registrations belong to the previous process and are replaced on the next launch.

## Repository and installation

The GitHub repository remains [ingussp/IP-Nesting](https://github.com/ingussp/IP-Nesting),
and an existing installation stays in its `Mod/IP-Nesting` folder. The folder name
does not determine the visible workbench name. Avoid installing a second copy into
another Mod folder while the existing installation is present.

## Preferences and saved documents

Existing preferences remain under `BaseApp/Preferences/Mod/IPNesting`. Reusing this
storage path preserves language, rotation, search, GPU and engine installation
preferences. Newly created property groups are labelled **1st Nesting**.

The original `IPNesting…` FreeCAD property names and the `IPNestingGrainMatches`
document object identifier remain unchanged. These are persistent data identifiers,
not product captions. Keeping them lets the renamed modules read saved texture
groups, custom angles, source-type information and original placements without
converting or discarding the user's document data.

Translation message keys remain stable; the user-facing messages and diagnostic
module names use the new branding in every supplied language.

## Nesting engine interface

CLI-nesting remains a separate engine. Its repository, executable names and
`workbench-job-v1` protocol are unchanged. The `_ip_nesting` compatibility metadata
key and existing job/update lock names remain unchanged so the renamed workbench
can read previous results and coordinate with the same installed engine.

New session files identify the workbench as **1st Nesting**. Renaming the workbench
does not rewrite existing input, session or result files, change part geometry,
or replace the engine executable.
