# python
"""Run the selected checkout's regressions in isolated Modo with an explicit runtime."""
import io,json,os,sys,traceback,unittest
from pathlib import Path
import lx
from PySide2 import QtCore
root=Path(os.environ['MOONRAY_TEST_SOURCE']);folder=Path(os.environ['MOONRAY_TEST_RESULTS'])/'issue-regressions'
folder.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(root/'tests'))
(folder/'progress.txt').write_text('Starting discovery',encoding='utf-8')
report={'pid':os.getpid(),'runtime':os.environ.get('MOONRAY_TEST_RUNTIME',''),'source':str(root)}
try:
 class Progress(unittest.TextTestResult):
  def startTest(self,test):
   (folder/'progress.txt').write_text(test.id(),encoding='utf-8');super().startTest(test)
 suite=unittest.TestSuite()
 for pattern in os.environ.get('MOONRAY_TEST_PATTERNS','test_*.py').split(';'):
  suite.addTests(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=pattern))
 log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Progress).run(suite)
 (folder/'unittest.log').write_text(log.getvalue(),encoding='utf-8')
 report.update(tests=result.testsRun,passed=result.wasSuccessful(),failures=[{'test':t.id(),'traceback':v} for t,v in result.failures],
  errors=[{'test':t.id(),'traceback':v} for t,v in result.errors],skipped=[{'test':t.id(),'reason':v} for t,v in result.skipped])
except BaseException:report['exception']=traceback.format_exc()
(folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
