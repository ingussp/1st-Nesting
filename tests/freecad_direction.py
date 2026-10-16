"""Native Qt selector, persistent identifiers, localization and JSON export."""
from pathlib import Path
from unittest.mock import patch
import json
import unittest
from freecad_bridges import App, QtGui, APPLICATION, languages
from Nesting1stGui import NestingTaskPanel
from Nesting1stExport import build_nesting_config, _read_fill_direction


class Preferences:
    def __init__(self): self.values={}
    def GetString(self,key,default=''):return self.values.get(key,default)
    def GetBool(self,key,default=False):return self.values.get(key,default)
    def GetInt(self,key,default=0):return self.values.get(key,default)
    def GetFloat(self,key,default=0):return self.values.get(key,default)
    def GetUnsigned(self,key,default=0):return self.values.get(key,default)
    def __getattr__(self,name):
        if name.startswith('Set'):return lambda key,value:self.values.__setitem__(key,value)
        if name.startswith('Rem'):return lambda key:self.values.pop(key,None)
        raise AttributeError(name)


class DirectionTests(unittest.TestCase):
    def setUp(self):
        languages._active_language='en'
        self.prefs=Preferences()
        with patch.object(App,'ParamGet',return_value=self.prefs):self.panel=NestingTaskPanel()
        self.panel._prefs=lambda:self.prefs
    def tearDown(self):
        self.panel._thickness_checker.timer.stop()
        self.panel._nesting_manager.shutdown()
        self.panel._selection_observer._unregister()
        self.panel.form.close()
        self.panel.form.deleteLater()
        languages._active_language='en'
        for name in list(App.listDocuments()):App.closeDocument(name)

    def test_two_choices_default_and_layout_above_gpu(self):
        combo=self.panel.fill_direction_combo
        self.assertEqual(combo.count(),2)
        self.assertEqual(_read_fill_direction(self.panel),'narrow-to-wide')
        self.panel.form.resize(1300,900);self.panel.form.show();APPLICATION.processEvents()
        self.assertLess(combo.mapTo(self.panel.form,combo.rect().topLeft()).y(),
                        self.panel.gpu_enabled_combo.mapTo(self.panel.form,self.panel.gpu_enabled_combo.rect().topLeft()).y())

    def test_saved_choice_uses_item_data_and_survives_language_switch(self):
        self.panel.fill_direction_combo.setCurrentIndex(1)
        self.assertEqual(self.prefs.GetString('FillDirection'),'wide-to-narrow')
        languages._active_language='lv'
        import FreeCADGui as Gui
        with patch.object(Gui,'getMainWindow',return_value=None,create=True):languages.refresh_ui()
        self.assertEqual(self.panel.fill_direction_combo.currentText(),'No platākās uz šaurāko pusi')
        self.assertEqual(_read_fill_direction(self.panel),'wide-to-narrow')
        self.panel.fill_direction_combo.blockSignals(True)
        self.panel.fill_direction_combo.setCurrentIndex(0)
        self.panel.fill_direction_combo.blockSignals(False)
        self.panel._load_settings_from_prefs()
        self.assertEqual(_read_fill_direction(self.panel),'wide-to-narrow')

    def test_config_is_identical_in_mm_and_inches(self):
        for units in ('mm','inch'):
            self.panel.display_units=units
            for index,value in enumerate(('narrow-to-wide','wide-to-narrow')):
                self.panel.fill_direction_combo.setCurrentIndex(index)
                config=build_nesting_config(fill_direction=_read_fill_direction(self.panel),spacing=2.54)
                self.assertEqual(config['fillDirection'],value)
                self.assertEqual(config['spacing'],2.54)
        self.assertEqual(build_nesting_config(fill_direction='unsupported')['fillDirection'],'narrow-to-wide')

    def test_all_50_languages_have_both_options(self):
        folder=Path(__file__).resolve().parents[1]/'lng'
        for language in json.loads((folder/'index.json').read_text(encoding='utf-8')):
            code=language['code'];catalog=json.loads((folder/(code+'.json')).read_text(encoding='utf-8'))
            for key in ('fill_direction','fill_direction_narrow_to_wide','fill_direction_wide_to_narrow'):
                self.assertTrue(catalog[key],(code,key))


if __name__=='__main__':unittest.main()
