# python
"""Exercise an unpacked content library in an isolated graphical Modo profile.

Set MOONRAY_TEST_KIT to the expected kit root; the probe refuses a different kit.
Use launch_gui_probe.py --kit-source KIT --profile NEW_PROFILE --wait.
MOONRAY_TEST_KIT must name the copied kit inside NEW_PROFILE/Configs/MoonRayForModo.
No scene is imported, rendered, or saved. Results/screenshots go to MOONRAY_TEST_RESULTS.
"""
import json,os,tempfile,time,traceback
from pathlib import Path
import lx
from PySide2 import QtCore,QtWidgets
out=Path(os.environ.get('MOONRAY_TEST_RESULTS',str(Path(tempfile.gettempdir())/'MoonRayForModo-tests')))/'content-library'
out.mkdir(parents=True,exist_ok=True)
result={'ok':False};browser=None;began=time.monotonic()
def finish(error=None):
    result['ok']=error is None
    if error:result['error']=error
    (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if browser:browser.close()
    QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
def inspect():
    try:
        if browser.timer.isActive() or browser.painter.isActive():
            if time.monotonic()-began>45:raise RuntimeError('Library scan/thumbnail timeout')
            QtCore.QTimer.singleShot(100,inspect);return
        assert browser.isVisible(),'Library window did not open'
        items=[browser.list.item(i) for i in range(browser.list.count())]
        scenes=[i for i in items if Path(i.data(QtCore.Qt.UserRole)['path']).suffix.lower()=='.rdla']
        expected=list(asset_library.bundled().rglob('*.rdla'))
        assert expected and len(scenes)==len(expected),(len(scenes),len(expected))
        paths={Path(i.data(QtCore.Qt.UserRole)['path']).resolve() for i in items}
        for scene in expected:
            if scene.with_suffix('.rdlb').is_file():assert scene.with_suffix('.rdlb').resolve() not in paths,'Paired binary listed twice'
        categories=browser.category.findItems('Example scenes',QtCore.Qt.MatchExactly)
        assert categories,'No example-scene category'
        browser.category.setCurrentItem(categories[0])
        assert all(i.isHidden() or i.data(QtCore.Qt.UserRole)['category']=='Example scenes' for i in items)
        browser.list.setCurrentItem(scenes[0]);browser.selection()
        assert browser.use.isEnabled() and browser.use.text()=='Open in the Import Dialog'
        assert browser.shown.pixmap() and not browser.shown.pixmap().isNull(),'No selected asset picture'
        browser.search.setText('___no_asset_matches_this___')
        assert all(i.isHidden() for i in items),'Search did not filter'
        browser.search.clear()
        assert not scenes[0].isHidden(),'Clearing search did not restore scene'
        assert browser.grab().save(str(out/'library.png')),'Cannot save evidence image'
        result.update(visible_assets=len(items),example_scenes=len(scenes),paired_files_deduplicated=True,category_filter=True,search_clear=True,selection_action=True)
        finish()
    except Exception:finish(traceback.format_exc())
try:
    from moonray_modo import asset_browser,asset_library
    expected=Path(os.environ['MOONRAY_TEST_KIT']).resolve()
    actual=Path(asset_browser.__file__).resolve().parents[2]
    assert actual==expected,('Wrong kit loaded',str(actual),str(expected))
    result['kit']=str(actual)
    # Keep the user's library roots untouched, even though asset settings use their own QSettings namespace.
    browser=asset_browser.Browser();browser.roots=[];browser.refresh();browser.show()
    QtCore.QTimer.singleShot(100,inspect)
except Exception:finish(traceback.format_exc())
