"""Denoise retained preview pixels without touching the renderer session."""
from pathlib import Path
import shutil
import tempfile
from PySide2 import QtCore
from . import denoising, native

class CachedDenoise(QtCore.QObject):
    def __init__(self, cache):
        super().__init__(cache)
        self.cache=cache;self.job=None;self.requested=None;self.directory=None
        self.process=QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.process.readAllStandardOutput)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.error)

    def request(self, engine):
        frame=self.cache.frame
        if frame is not None and frame.get('snapshot',{}).get('_ipr'):engine='off'
        self.requested=engine
        if self.job is not None:return
        frame=self.cache.frame
        if engine=='off' or frame is None:return
        if frame.get('denoise_engine')==engine and 'denoised_beauty' in frame['files']:return
        try:
            self.directory=tempfile.TemporaryDirectory(prefix='MoonRayDenoise-')
            root=Path(self.directory.name);files=frame['files'];guides={}
            before=[];oiio=Path(frame['runtime'])/'oiiotool.exe';takes=frame.get('takes',{})
            # A render stopped part way has pixels MoonRay was adding to as its picture was taken. In the denoiser's
            # guides they stand out from those beside them, some too dark and some, on a grid of every other pixel
            # where a tile was being begun, several times too bright; and the denoiser draws a speck at each. So
            # the guides of such a render are put right first. A normal is as long as any other, whatever was
            # caught of it: each is brought to its full length, and one that is nothing among others that are
            # something takes their direction. The albedo takes the middle value of each pixel and those touching
            # it, which a grid of every other pixel never is. The beauty is noisy of itself and is left so, but for
            # a pixel four times as bright as the middle of those about it, or a quarter as bright, which is
            # brought to that.
            repair={'denoise_normal':['--dup','--median','5x5','--mulc','0.001','--add','--normalize:incenter=0:outcenter=0:scale=1'],
                    'denoise_albedo':['--median','3x3'],
                    'beauty':['--dup','--median','5x5','--mulc','4','--min','--dup','--median','5x5','--mulc','0.25','--max']}
            for key in ('beauty','denoise_albedo','denoise_normal'):
                target=root/(key+'.exr')
                if len(takes.get(key,()))==3:
                    # Kept from a pass in progress, in three takes: the middle value of each pixel is what stands,
                    # so that a pixel caught while MoonRay was adding to it leaves no mark.
                    a,b,c=[root/('%s-%d.pfm'%(key,index)) for index in range(3)]
                    for source,held in zip(takes[key],(a,b,c)):shutil.copyfile(str(source),str(held))
                    before.append((oiio,[str(a),str(b),'--min',str(a),str(b),'--max',str(c),'--min','--max']+repair.get(key,[])+['-d','float','-o',str(target)],target))
                elif Path(files[key]).suffix.lower()!='.exr':
                    held=root/(key+'-held'+Path(files[key]).suffix)
                    shutil.copyfile(str(files[key]),str(held))
                    before.append((oiio,[str(held)]+(repair.get(key,[]) if key in takes else [])+['-d','float','-o',str(target)],target))
                else:shutil.copyfile(str(files[key]),str(target))
            beauty=root/'beauty.exr'
            guides={key:str(root/('denoise_'+key+'.exr')) for key in ('albedo','normal')}
            self.jobs=before+denoising.jobs(frame['runtime'],beauty,root/'result',engine,guides)
            self.result=self.jobs[-1][2];self.job=(frame,engine)
            env=QtCore.QProcessEnvironment()
            for key,value in native.environment(frame['runtime']).items():env.insert(key,value)
            self.process.setProcessEnvironment(env)
            self.cache.notice.emit('Denoising completed beauty — no rerender')
            self.next()
        except Exception as exc:
            self.cleanup();self.cache.notice.emit('Cannot denoise cached beauty: '+str(exc))

    def next(self):
        program,args,self.expected=self.jobs.pop(0)
        self.process.setProgram(str(program));self.process.setArguments(args);self.process.start()

    def finished(self, code, status):
        if self.job is None:return
        if code or status!=QtCore.QProcess.NormalExit or not self.expected.is_file():
            self.cleanup();self.cache.notice.emit('Denoising failed; original beauty remains available.');return
        if self.jobs:self.next();return
        frame,engine=self.job
        if self.cache.frame is frame and not self.cache.closed and self.requested==engine:
            try:
                target=frame['folder']/('denoised-'+engine+'.exr')
                shutil.copyfile(str(self.result),str(target))
                frame['files']['denoised_beauty']=target;frame['denoise_engine']=engine
                self.cache.serial+=1;self.cache._request()
                self.cache.notice.emit('Denoised Beauty ready')
            except OSError as exc:self.cache.notice.emit('Cannot retain denoised beauty: '+str(exc))
        repeat=self.cache.frame is not frame or self.requested!=engine
        self.cleanup()
        if repeat and not self.cache.closed:self.request(self.requested)

    def error(self, error):
        if error==QtCore.QProcess.FailedToStart:
            self.cleanup();self.cache.notice.emit('Cannot start denoiser: '+self.process.errorString())

    def cleanup(self):
        self.job=None
        if self.directory:
            try:self.directory.cleanup()
            except OSError:pass
            self.directory=None

    def close(self):
        self.requested='off'
        self.job=None  # Ignore completion callbacks from intentional cancellation.
        if self.process.state()!=QtCore.QProcess.NotRunning:
            self.process.kill();self.process.waitForFinished(2000)
        self.cleanup()
