from Nesting1stLanguages import SettingsCommand

import FreeCADGui as Gui

# Register the 1st Nesting workbench and its toolbar in FreeCAD.
class Nesting1stWorkbench(Workbench):
    MenuText = "1st Nesting"
    
    # Using your color #CF3519 for the placeholder icon
    Icon = """
    /* XPM */
    static char * xpm_icon[] = {
    "16 16 2 1",
    "  c None",
    ". c #CF3519",
    "                ",
    "  ............  ",
    "  .          .  ",
    "  .  ......  .  ",
    "  .  .    .  .  ",
    "  .  .    .  .  ",
    "  .  ......  .  ",
    "  .          .  ",
    "  .  ......  .  ",
    "  .  .    .  .  ",
    "  .  .    .  .  ",
    "  .  ......  .  ",
    "  .          .  ",
    "  ............  ",
    "                ",
    "                "};
    """

    # Resolve translations locally because FreeCAD may execute this script with separate namespaces.
    def __init__(self):
        from Nesting1stLanguages import tr
        self.ToolTip = tr('optimal_parts_nesting_on_a_sheet')

    # Load the nesting panel and place Settings next to Run Nesting in the toolbar.
    def Initialize(self):
        import Nesting1stGui
        self.appendToolbar("1st Nesting Tools", ["Nesting1st_RunNesting", "Nesting1st_Settings"])
        self.appendMenu("1st Nesting", ["Nesting1st_RunNesting", "Nesting1st_Settings"])

    # Return the FreeCAD Python workbench type identifier.
    def GetClassName(self): 
        return "Gui::PythonWorkbench"

    def Activated(self):
        from Nesting1stEngineUI import offer_first_run
        offer_first_run()

# Expose the command that opens the nesting task panel.
class RunNestingCommand:
    # Return the command label, tooltip and custom icon path, with an icon fallback.
    def GetResources(self):
        import os
        from Nesting1stLanguages import tr, DIRECTORY

        # Path to your custom png icon
        icon_path = os.path.join(DIRECTORY, "icons/nesting_icon.png")
        
        return {
            'MenuText': tr('nesting_tool'),
            'ToolTip': tr('open_the_nesting_configuration_panel'),
            'Pixmap': icon_path if os.path.exists(icon_path) else 'Part_Box' # Fallback to standard icon
        }

    # Open the nesting panel and attempt to add the current non-preview selection.
    def Activated(self):
        import traceback
        import FreeCAD as App
        import FreeCADGui as Gui
        from Nesting1stLanguages import tr

        # Create and show the panel
        import Nesting1stGui
        panel = Nesting1stGui.NestingTaskPanel()
        Gui.Control.showDialog(panel)
        from Nesting1stEngineUI import offer_first_run
        offer_first_run()

        # Automatic add: if user already has selection in the main document (not the preview),
        # call panel.add_selected_objects() so the selected bodies are copied into the preview/table.
        try:
            sel = Gui.Selection.getSelection()
            if sel:
                # ensure selection is not already from the preview document
                try:
                    first_doc_name = sel[0].Document.Name if getattr(sel[0], "Document", None) else None
                except Exception:
                    first_doc_name = None
                if first_doc_name and first_doc_name != panel.preview_doc_name:
                    try:
                        panel.add_selected_objects()
                    except Exception:
                        App.Console.PrintError(tr('runnestingcommand_failed_to_auto_add_selected_objects') + traceback.format_exc())
        except Exception:
            # silently continue if selection can't be read
            pass

    # Return the Python workbench type string exposed by this command.
    def GetClassName(self):
        return "Gui::PythonWorkbench"

Gui.addCommand('Nesting1st_RunNesting', RunNestingCommand())
Gui.addCommand('Nesting1st_Settings', SettingsCommand())
Gui.addWorkbench(Nesting1stWorkbench())
