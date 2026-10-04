# python
"""Run regression tests in a disposable Modo 16.1v9 profile, then quit that instance."""
import io,json,os,sys,traceback,unittest
from pathlib import Path
import lx
from PySide2 import QtCore
ROOT=Path('C:/Users/Raphael Tobar/MoonRayForModo')
folder=ROOT/'test-results/regression-0332-host';folder.mkdir(parents=True,exist_ok=True)
(folder/'progress.txt').write_text('Started in Modo',encoding='utf-8')
os.environ['MOONRAY_TEST_RUNTIME']=str(ROOT/'runtime/xpu-adaptive-buckets-0332')
sys.path.insert(0,str(ROOT/'tests'))
report={'pid':os.getpid(),'runtime':os.environ['MOONRAY_TEST_RUNTIME']}
try:
    class Progress(unittest.TextTestResult):
        def startTest(self,test):
            (folder/'progress.txt').write_text(test.id(),encoding='utf-8')
            super().startTest(test)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Progress).run(suite)
    (folder/'unittest.log').write_text(log.getvalue(),encoding='utf-8')
    report.update(tests=result.testsRun,passed=result.wasSuccessful(),failures=[{'test':t.id(),'traceback':v} for t,v in result.failures],errors=[{'test':t.id(),'traceback':v} for t,v in result.errors],skipped=[{'test':t.id(),'reason':v} for t,v in result.skipped])
except BaseException:report['exception']=traceback.format_exc()
(folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
QtCore.QTimer.singleShot(0,lambda:lx.eval('!app.quit'))