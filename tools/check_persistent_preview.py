"""Deferred native session check. Run explicitly; never opens or changes Modo."""
import argparse,copy,hashlib,os,queue,subprocess,sys,threading,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'kit/MoonRayForModo/python'))
from moonray_modo import native,rdla
from moonray_modo.scene_delta import difference


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime',type=Path)
    args=parser.parse_args();runtime=native.find_runtime(args.runtime)
    out=root/'test-results'/('persistent-'+time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True,exist_ok=False)
    scene={'camera':{'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,4,1],'focal_mm':50,'film_mm':36},
           'materials':{'':{'color':[.7,.1,.1]}},'lights':[],
           'meshes':[{'name':'quad','vertices':[[-.5,-.5,0],[.5,-.5,0],[.5,.5,0],[-.5,.5,0]],
                      'faces':[[0,1,2,3]],'material':'','matrix':rdla.IDENTITY[:]}],
           'render_settings':{'sampling_mode':0},'preview_buffer':'beauty'}
    def serialize(value,generation):
        value=copy.deepcopy(value);value['preview_buffer_file']=str(out/('%d.buffer.exr'%generation))
        text=rdla.scene_text(value,64,64,1,1)
        path=out/('%d.full.rdla'%generation);path.write_text(text,encoding='utf-8')
        return text,path
    previous,source=serialize(scene,1)
    env=native.environment(runtime);env['MOONRAY_MODO_SESSION']=str(out);env['MOONRAY_MODO_GENERATION']='1'
    messages=queue.Queue()
    process=subprocess.Popen([str(runtime/'moonray.exe')]+native.arguments(source,out/'main.exr',4,'scalar'),
        cwd=out,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    pid=process.pid
    def reader():
        with (out/'session.log').open('wb') as log:
            for line in iter(process.stdout.readline,b''):
                log.write(line);log.flush()
                messages.put(line.decode('utf-8',errors='replace').strip())
        messages.put('EXIT')
    thread=threading.Thread(target=reader,daemon=True);thread.start()
    def wait_done(generation):
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            try:line=messages.get(timeout=1)
            except queue.Empty:continue
            if line=='@@MODO_SESSION DONE %d'%generation:break
            if line=='EXIT':raise RuntimeError('Renderer exited; inspect '+str(out/'session.log'))
        else:raise TimeoutError('Session did not complete frame %d'%generation)
        assert process.pid==pid and process.poll() is None
        image=out/('%d.buffer.exr'%generation);assert image.is_file() and image.stat().st_size>16
        png=out/('%d.png'%generation)
        subprocess.run([str(runtime/'oiiotool.exe'),str(image),'-o',str(png)],env=native.environment(runtime),check=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        return hashlib.sha256(png.read_bytes()).hexdigest()
    try:
        first=wait_done(1)
        scene['meshes'][0]['matrix'][12]=.7
        current,full=serialize(scene,2);delta=difference(previous,current)
        assert delta is not None and 'node_xform' in delta and 'vertex_list_0' not in delta
        update=out/'2.delta.rdla';update.write_text(delta,encoding='utf-8')
        command=out/'command.tmp';command.write_text('2\ndelta\n%s\n%s\n'%(update.as_posix(),full.as_posix()),encoding='utf-8');command.replace(out/'command.txt')
        second=wait_done(2);assert first!=second,'Moved object did not change image pixels'
        previous=current;scene['meshes'].append(copy.deepcopy(scene['meshes'][0]));scene['meshes'][1]['matrix'][12]=-.7
        current,full=serialize(scene,3);assert difference(previous,current) is None
        command.write_text('3\nfull\n%s\n%s\n'%(full.as_posix(),full.as_posix()),encoding='utf-8');command.replace(out/'command.txt')
        third=wait_done(3);assert third!=second,'Structural scene reload did not change image'
        command.write_text('4\nquit\n-\n-\n',encoding='utf-8');command.replace(out/'command.txt')
        assert process.wait(timeout=30)==0
        print('Same process rendered initial, delta and full-reload images:',pid)
        print('Reports:',out)
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=10)
        thread.join(timeout=5)

if __name__=='__main__':main()
