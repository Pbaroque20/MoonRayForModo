"""Standalone private preview for frozen scene packages. Never installs a Modo kit."""
import argparse,array,json,math,threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from protocol_model import Epoch
from prototype_service import PrototypeService
HERE=Path(__file__).resolve().parent

def display_ppm(frame):
    """Display-only sRGB on black, with native raw float32 bytes untouched."""
    values=array.array('f');values.frombytes(frame.rgba);width,height=frame.width,frame.height
    def encode(v):
        v=max(0.0,min(1.0,v));return int(255*(12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055)+.5)
    data=bytearray(width*height*3)
    for y in range(height):
        for x in range(width):
            source=((height-1-y)*width+x)*4;target=(y*width+x)*3
            for c in range(3):data[target+c]=encode(values[source+c])
    return f'P6\n{width} {height}\n255\n'.encode()+data

class DisplayWorker:
    def __init__(self):
        self.lock=threading.Lock();self.wake=threading.Event();self.pending=None;self.result=None;self.closing=False
        self.thread=threading.Thread(target=self.run,name='XPU2-display',daemon=True);self.thread.start()
    def submit(self,frame):
        with self.lock:self.pending=frame;self.result=None
        self.wake.set()
    def poll(self):
        with self.lock:result=self.result;self.result=None;return result
    def clear(self):
        with self.lock:self.pending=None;self.result=None
    def close(self):
        with self.lock:self.closing=True;self.pending=None;self.result=None
        self.wake.set()
    def run(self):
        while True:
            self.wake.wait();self.wake.clear()
            with self.lock:
                if self.closing:return
                frame=self.pending;self.pending=None
            if frame is not None:
                ppm=display_ppm(frame)
                with self.lock:
                    if not self.closing and self.pending is None:self.result=(frame,ppm)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','runtime','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--manifest',type=Path)
    p.add_argument('--fine-textures',action='store_true',help='Private opt-in 64 MiB GPU texture refill')
    p.add_argument('--publish-ms',type=int,default=0,help='Private display cadence; 33 avoids excessive full-film copies')
    a=p.parse_args();build=json.loads(a.build.read_text());assert build['status']=='passed'
    service=PrototypeService(build['exe'],build['ptx'],a.runtime.resolve(),json.loads((HERE/'reference-lock.json').read_text()),a.output.resolve(),binary_hashes=build['binary_hashes'])
    display=DisplayWorker();root=tk.Tk();root.title('XPU2 — private prototype');root.geometry('840x670')
    controls=ttk.Frame(root,padding=10);controls.pack(fill='x')
    scene=tk.StringVar(value=str(a.manifest.resolve()) if a.manifest else '')
    ttk.Entry(controls,textvariable=scene,width=75).grid(row=0,column=0,columnspan=4,sticky='ew')
    def choose():
        selected=filedialog.askopenfilename(title='Select frozen scene manifest',filetypes=[('Frozen scene','manifest.json')])
        if selected:scene.set(selected)
    ttk.Button(controls,text='Open…',command=choose).grid(row=0,column=4,padx=5)
    native=tk.BooleanVar(value=False);ttk.Checkbutton(controls,text='Experimental CPU/GPU preview',variable=native).grid(row=1,column=0,sticky='w')
    domain=tk.StringVar(value='surface-textures');ttk.Combobox(controls,textvariable=domain,values=('surface-textures','planar-textures','diffuse-mesh'),state='readonly',width=20).grid(row=1,column=1)
    status=tk.StringVar(value='Choose a frozen scene. Native preview is opt-in; unsupported scenes use reference XPU.')
    ttk.Label(root,textvariable=status,wraplength=810,padding=10).pack(fill='x')
    canvas=tk.Canvas(root,background='#151719',highlightthickness=0);canvas.pack(fill='both',expand=True)
    ttk.Label(root,text='Display: sRGB on black, highlights clipped. Raw float32 output is retained separately. No speed or fidelity qualification.',wraplength=810,padding=10).pack(fill='x')
    generation=0;seen=None;photo=None;closing=False;shown=None
    def clear():
        nonlocal seen,photo,shown
        seen=photo=shown=None;display.clear();canvas.delete('all')
    def render():
        nonlocal generation
        try:
            generation+=1;service.request(Path(scene.get()).absolute(),Epoch(2001,generation,1,1),12,experimental_native=native.get(),domain=domain.get(),refill_fine=a.fine_textures and native.get(),publish_ms=a.publish_ms);clear()
        except Exception as error:status.set(str(error))
    def cancel():service.cancel();clear()
    ttk.Button(controls,text='Render',command=render).grid(row=1,column=2,padx=6,pady=10)
    ttk.Button(controls,text='Cancel',command=cancel).grid(row=1,column=3)
    def close():
        nonlocal closing
        closing=True;service.close();display.close();clear();status.set('Closing owned render processes…')
    root.protocol('WM_DELETE_WINDOW',close)
    def tick():
        nonlocal seen,photo,shown
        s=service.poll()
        if closing:
            if service.wait_closed(0):root.destroy();return
        else:
            if s.frame is None:
                if shown is not None or seen is not None:clear()
                status.set(s.phase+((': '+s.error) if s.error else (': '+s.fallback_reason if s.fallback_reason else '')))
            else:
                f=s.frame
                if f is not seen:seen=f;display.submit(f)
                tier='MoonRay reference (F)' if f.tier=='F' else 'Experimental native preview (D)'
                status.set(tier+' — '+('complete' if f.final else str(f.min_spp)+' minimum spp')+(' — fallback: '+s.fallback_reason if s.fallback_reason else ''))
            result=display.poll()
            if result is not None:
                frame,ppm=result
                # Discard late conversion after cancellation, edit or fallback.
                if s.frame is not None and frame.ticket==s.ticket and frame.tier==s.frame.tier:
                    photo=tk.PhotoImage(data=ppm,format='PPM');scale=max(1,min(8,min(max(1,canvas.winfo_width()//frame.width),max(1,canvas.winfo_height()//frame.height))))
                    if scale>1:photo=photo.zoom(scale)
                    canvas.delete('all');canvas.create_image(canvas.winfo_width()/2,canvas.winfo_height()/2,image=photo,anchor='center');shown=frame
        root.after(33,tick)
    tick()
    try:root.mainloop()
    finally:service.close();display.close();service.wait_closed(25);display.thread.join(5)
if __name__=='__main__':main()
