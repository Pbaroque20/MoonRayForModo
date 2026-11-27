# python
"""Command line: Blobs and Sprites whose particles come from a real emitter or a cache, as the kit reads them frame by
frame. Steps (MOONRAY_PROBE_STEP, a comma list):
  explore - a Radial Emitter made (with the Particle Simulation it makes) and a CSV Point Cache: their items, graphs
            and channels
  sim     - a Radial Emitter at (0, 1, 0) (rate 60 a second, 1.5 m/s, gravity on, particles die at 2 s) feeding its
            Particle Simulation; a Blob (Radius 0.12) and a Sprite (Radius 0.3, at x 3) on it. At frames 1, 12, 24, 48
            the particles as particles.read gives them (count, features, first few: id, size, velocity, age, dissolve)
            and the kit's reading (the blob's faces, the sprite's file, notices). Saved as sim.lxo; frame 24 rendered
            by Modo (sim.exr) when MOONRAY_PROBE_RENDER is set.
  csv     - a CSV Point Cache over a sequence of files written here (frames 1 to 10: a ring of 40 points turning) with a
            Blob on it: the same report per frame. Saved as csv.lxo.
Writes report.json into MOONRAY_PROBE_OUT."""
import json
import math
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or 'test-results/particle-sim')
out.mkdir(parents=True, exist_ok=True)
steps = [s for s in os.environ.get('MOONRAY_PROBE_STEP', 'explore').split(',') if s]
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def describe(item):
    held = {'type': item.type, 'name': item.name}
    chans = {}
    for c in item.channels():
        try:
            v = c.get()
            if 'Unknown' not in str(v):
                chans[c.name] = v
        except Exception as exc:
            chans[c.name] = '? %s' % exc
    held['channels'] = chans
    graphs = {}
    for g in ('particle', 'particleOp', 'particleSim', 'emitSource', 'source', 'pointCache', 'dynamic'):
        try:
            fwd = [i.name for i in item.itemGraph(g).forward()]
            rev = [i.name for i in item.itemGraph(g).reverse()]
            if fwd or rev:
                graphs[g] = {'forward': fwd, 'reverse': rev}
        except Exception:
            pass
    held['graphs'] = graphs
    return held


def volume_on(scene, kind, name, source, **channels):
    item = scene.addItem(kind, name=name)
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('volume.particle {%s}' % source.id)
    for key, value in channels.items():
        item.channel(key).set(value)
    return item


def features(item, seconds):
    from moonray_modo import particles
    found = particles.surface(item, seconds)
    if found is None:
        return None
    kind = lx.symbol.iTBLX_PARTICLES
    return [found.FeatureByIndex(kind, i) for i in range(found.FeatureCount(kind))]


def raw_values(item, seconds, names=('pos', 'id', 'size', 'vel', 'age', 'dissolve'), first=4):
    """The first particles with each feature named, as Modo hands them over."""
    from moonray_modo import particles
    found = particles.surface(item, seconds)
    if found is None:
        return None
    kind = lx.symbol.iTBLX_PARTICLES
    have = [found.FeatureByIndex(kind, i) for i in range(found.FeatureCount(kind))]
    wanted = [n for n in names if n in have]
    vertex = lx.service.Tableau().AllocVertex()
    widths = {}
    for n in wanted:
        vertex.AddFeature(kind, n)
        widths[n] = 3 if n in ('pos', 'vel') else 1
    found.SetVertex(vertex)
    soup = particles._soup()(vertex.Size())
    found.Sample(((-1e30, -1e30, -1e30), (1e30, 1e30, 1e30)), -1.0, soup)
    size = vertex.Size()
    rows = []
    for i in range(min(first, soup.count)):
        at, row = i * size, {}
        for n in wanted:
            row[n] = [round(v, 4) for v in soup.values[at:at + widths[n]]]
            at += widths[n]
        rows.append(row)
    return {'count': soup.count, 'size': size, 'first': rows}


def per_frame(scene, items, frames, tag):
    from moonray_modo import particles, host
    fps = float(scene.fps)
    held = report.setdefault(tag, {})
    for frame in frames:
        seconds = frame / fps
        lx.service.Selection().SetTime(seconds)
        entry = held.setdefault(str(frame), {})
        for item in items:
            try:
                started = time.perf_counter()
                read = particles.read(item, seconds)
                entry[item.name] = {'features': features(item, seconds), 'raw': raw_values(item, seconds),
                                    'read count': len(read['ids']) if read else 0, 'read seconds': round(time.perf_counter() - started, 3),
                                    'ids first': [round(v, 4) for v in read['ids'][:4]] if read else None,
                                    'sizes first': [round(v, 4) for v in read['sizes'][:4]] if read and read.get('sizes') is not None else None,
                                    'velocities': read['velocities'] is not None if read else None}
            except Exception:
                entry[item.name] = {'error': traceback.format_exc()}
        try:
            snapshot = host.snapshot()
            entry['kit'] = {'meshes': [{'name': m['name'], 'faces': len(m['faces']), 'velocities': 'velocities' in m} for m in snapshot['meshes'] if m.get('_particles')],
                            'volumes': [{'name': e['name'], 'file': e['file'], 'velocity grid': e.get('velocity_grid')} for e in snapshot.get('extra_geometry', []) if e.get('_particles')],
                            'points': [e['name'] for e in snapshot.get('extra_geometry', []) if e.get('kind') == 'points'],
                            'warnings': snapshot.get('warnings'), 'seconds': snapshot.get('_particle_seconds')}
        except Exception:
            entry['kit'] = {'error': traceback.format_exc()}
        save()


try:
    if 'explore' in steps:
        lx.eval('scene.new')
        scene = modo.Scene()
        before = {i.id for i in scene.items()}
        lx.eval('item.create radialEmitter')
        report['made by radialEmitter'] = [describe(i) for i in scene.items() if i.id not in before and i.type not in ('translation', 'rotation', 'scale')]
        before = {i.id for i in scene.items()}
        lx.eval('item.create csvCache')
        report['made by csvCache'] = [describe(i) for i in scene.items() if i.id not in before and i.type not in ('translation', 'rotation', 'scale')]
        save()
    if 'sim' in steps:
        lx.eval('scene.new')
        scene = modo.Scene()
        before = {i.id for i in scene.items()}
        lx.eval('item.create radialEmitter')
        made = [i for i in scene.items() if i.id not in before]
        emitter = next(i for i in made if i.type == 'radialEmitter')
        sim = next(i for i in made if i.type == 'particleSim')
        modo.LocatorSuperType(emitter).position.set((0.0, 1.0, 0.0))
        for key, value in (('rate', 60.0), ('velocity', 1.5)):
            emitter.channel(key).set(value)
        for key, value in (('gravEnable', 1), ('ageKill', 1), ('ageMax', 2.0)):
            sim.channel(key).set(value)
        blob = volume_on(scene, 'blob', 'Sim blob', sim, radius=0.12)
        sprite = volume_on(scene, 'sprite', 'Sim sprite', sim, radius=0.3, texAmplitude=0.0)
        modo.LocatorSuperType(sim).position.set((0.0, 0.0, 0.0))
        report['sim items'] = [describe(i) for i in (emitter, sim, blob)]
        save()
        camera = scene.renderCamera
        camera.position.set((0.0, 1.2, 7.0))
        camera.rotation.set((-0.05, 0.0, 0.0))
        render_item = scene.renderItem
        for key, value in (('resX', 640), ('resY', 360), ('first', 24), ('last', 24)):
            render_item.channel(key).set(value)
        lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'sim.lxo'))
        # Not cached: what the kit says.
        per_frame(scene, [blob, sprite], (24,), 'sim uncached')
        # Modo's Dynamics > Cache Simulation over 0 to 2 s, then frame by frame.
        lx.eval('!simulate 0.0 2.0')
        per_frame(scene, [blob, sprite], (1, 12, 24, 47), 'sim')
        if os.environ.get('MOONRAY_PROBE_RENDER'):
            lx.service.Selection().SetTime(24 / float(scene.fps))
            lx.eval('!render.animation {%s} openexr' % (out / 'sim'))
            report['sim rendered'] = sorted(p.name for p in out.glob('sim*'))
            save()
            # The scene as the kit exports it at frame 24, for MoonRay.
            from moonray_modo import scene_export
            written = scene_export.export({'path': out / 'sim.0024.rdla', 'format': 'rdla', 'outputs': True, 'collect': False, 'frames': False}, [])
            report['sim exported'] = [str(p) for p in written]
            save()
    if 'sim2' in steps:
        # The simulation stepped frame by frame from the start (as Modo's timeline plays it).
        lx.eval('scene.open {%s} normal' % (out / 'sim.lxo'))
        scene = modo.Scene()
        from moonray_modo import particles
        blob = next(iter(scene.items('blob')))
        fps = float(scene.fps)
        try:
            report['autoUpdate'] = lx.eval('particle.autoUpdate ?')
        except Exception as exc:
            report['autoUpdate'] = str(exc)
        counts = {}
        for frame in range(0, 49):
            lx.service.Selection().SetTime(frame / fps)
            held = particles.read(blob, frame / fps)
            counts[frame] = len(held['ids']) if held else 0
        report['stepped counts'] = counts
        report['read at 12 after stepping'] = len((particles.read(blob, 12 / fps) or {'ids': []})['ids'])
        save()
        if os.environ.get('MOONRAY_PROBE_RENDER'):
            for sprite in scene.items('sprite'):
                sprite.channel('render').set('off')
            lx.eval('!render.animation {%s} openexr' % (out / 'sim'))
            report['sim rendered'] = sorted(p.name for p in out.glob('sim*'))
            lx.service.Selection().SetTime(24 / fps)
            report['read at 24 after the render'] = len((particles.read(blob, 24 / fps) or {'ids': []})['ids'])
            save()
    if 'sim3' in steps:
        # The simulation's own particles: its tgroup channel (a triangle group) through TriGroupToParticle, stepped
        # frame by frame, then after Modo has rendered frames 1 to 24 (its renderer runs the simulation from the first).
        lx.eval('scene.open {%s} normal' % (out / 'sim.lxo'))
        scene = modo.Scene()
        from moonray_modo import particles
        sim = next(iter(scene.items('particleSim')))
        blob = next(iter(scene.items('blob')))
        fps = float(scene.fps)

        def by_tgroup(seconds):
            chan = lx.object.ChannelRead(lx.object.Scene(sim._item.Context()).Channels(None, seconds))
            raw = lx.object.Item(sim._item)
            value = chan.ValueObj(raw, raw.ChannelLookup('tgroup'))
            interfaces = []
            for n in ('TriangleGroup', 'TableauSurface', 'ValueReference'):
                try:
                    if getattr(lx.object, n)(value).test():
                        interfaces.append(n)
                except TypeError:
                    pass
            try:
                ref = lx.object.ValueReference(value)
                if ref.test() and ref.IsSet():
                    value = ref.GetObject()
            except Exception:
                pass
            group = lx.object.TriangleGroup(value)
            if not group.test():
                return {'interfaces': interfaces, 'group': False}
            surface = lx.object.TableauSurface(lx.service.Particle().TriGroupToParticle(group))
            kind = lx.symbol.iTBLX_PARTICLES
            have = [surface.FeatureByIndex(kind, i) for i in range(surface.FeatureCount(kind))]
            vertex = lx.service.Tableau().AllocVertex()
            vertex.AddFeature(kind, 'pos')
            surface.SetVertex(vertex)
            soup = particles._soup()(vertex.Size())
            surface.Sample(((-1e30, -1e30, -1e30), (1e30, 1e30, 1e30)), -1.0, soup)
            return {'interfaces': interfaces, 'features': have, 'count': soup.count, 'groups': group.Count() if hasattr(group, 'Count') else None}
        stepped = {}
        for frame in (0, 1, 2, 6, 12, 24):
            lx.service.Selection().SetTime(frame / fps)
            try:
                stepped[frame] = by_tgroup(frame / fps)
            except Exception:
                stepped[frame] = traceback.format_exc()[-400:]
        report['tgroup stepped'] = stepped
        save()
        # Modo's Dynamics > Cache Simulation (simulate): the simulation computed over 0 to 2 s and cached.
        try:
            lx.eval('!simulate 0.0 2.0')
            report['simulate'] = 'ok'
        except Exception as exc:
            report['simulate'] = str(exc)
        after = {}
        for frame in (6, 12, 24):
            lx.service.Selection().SetTime(frame / fps)
            try:
                after[frame] = {'tgroup': by_tgroup(frame / fps), 'read': len((particles.read(blob, frame / fps) or {'ids': []})['ids'])}
            except Exception:
                after[frame] = traceback.format_exc()[-400:]
        report['after simulate'] = after
        save()
    if 'csv3' in steps:
        # Which header and file pattern Modo's CSV Point Cache reads (its own new sequences are named [####].CSV).
        heads = {'none': None, 'bracket': 'pos[0],pos[1],pos[2]', 'dot': 'pos.X,pos.Y,pos.Z', 'plain': 'posX,posY,posZ', 'under': 'pos_x,pos_y,pos_z',
                 'digit': 'pos0,pos1,pos2', 'xyz': 'x,y,z', 'same': 'pos,pos,pos', 'spaced': 'pos.X, pos.Y, pos.Z', 'lower': 'pos.x,pos.y,pos.z'}
        tried = {}
        for name, head in heads.items():
            folder = out / ('csv-' + name)
            folder.mkdir(exist_ok=True)
            for frame in range(0, 6):
                rows = ['%.4f,%.4f,%.4f' % (math.cos(k + frame * 0.1), 1.0, math.sin(k + frame * 0.1)) for k in range(8)]
                (folder / ('ring%04d.csv' % frame)).write_text('\n'.join(([head] if head else []) + rows) + '\n')
            for pattern in ('ring[####].csv',):
                lx.eval('scene.new')
                scene = modo.Scene()
                before = {i.id for i in scene.items()}
                lx.eval('item.create csvCache')
                cache = next(i for i in scene.items() if i.id not in before and i.type == 'csvCache')
                cache.channel('filePattern').set(str(folder / pattern).replace('\\', '/'))
                cache.channel('seqEnd').set(5)
                blob = volume_on(scene, 'blob', 'CSV blob', cache, radius=0.2)
                from moonray_modo import particles
                fps = float(scene.fps)
                found = {}
                for frame in (1, 3):
                    lx.service.Selection().SetTime(frame / fps)
                    held = particles.read(blob, frame / fps)
                    found[frame] = (len(held['ids']), held.get('features'), [round(v, 3) for v in held['positions'][:6]]) if held else 0
                tried['%s %s' % (name, pattern)] = found
                save()
        report['csv formats'] = tried
        save()
    if 'csv2' in steps:
        folder = out / 'csv'
        tried = {}
        for pattern in (str(folder / 'ring.0001.csv'), str(folder / 'ring.####.csv'), str(folder / 'ring.%04d.csv'), str(folder / 'ring.*.csv')):
            lx.eval('scene.new')
            scene = modo.Scene()
            before = {i.id for i in scene.items()}
            lx.eval('item.create csvCache')
            cache = next(i for i in scene.items() if i.id not in before and i.type == 'csvCache')
            cache.channel('filePattern').set(pattern.replace('\\', '/'))
            blob = volume_on(scene, 'blob', 'CSV blob', cache, radius=0.2)
            from moonray_modo import particles
            fps = float(scene.fps)
            found = {}
            for frame in (0, 1, 5):
                lx.service.Selection().SetTime(frame / fps)
                held = particles.read(blob, frame / fps)
                found[frame] = len(held['ids']) if held else 0
            tried[pattern] = {'counts': found, 'channels': describe(cache)['channels']}
        report['csv patterns'] = tried
        save()
    if 'csv' in steps:
        folder = out / 'csv'
        folder.mkdir(exist_ok=True)
        for frame in range(1, 11):
            turn = frame * 0.1
            lines = ['%.5f,%.5f,%.5f' % (math.cos(2 * math.pi * k / 40 + turn), 1.0 + 0.2 * math.sin(4 * math.pi * k / 40), math.sin(2 * math.pi * k / 40 + turn))
                     for k in range(40)]
            # A header line first (Modo's reader skips it), then a point a line.
            (folder / ('ring.%04d.csv' % frame)).write_text('\n'.join(['pos.X,pos.Y,pos.Z'] + lines) + '\n')
        lx.eval('scene.new')
        scene = modo.Scene()
        before = {i.id for i in scene.items()}
        lx.eval('item.create csvCache')
        cache = next(i for i in scene.items() if i.id not in before and i.type == 'csvCache')
        cache.channel('filePattern').set(str(folder / 'ring.[####].csv').replace('\\', '/'))
        for key, value in (('seqStart', 1), ('seqEnd', 10)):
            cache.channel(key).set(value)
        blob = volume_on(scene, 'blob', 'CSV blob', cache, radius=0.2)
        report['csv items'] = [describe(i) for i in (cache, blob)]
        lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'csv.lxo'))
        per_frame(scene, [blob], (1, 5, 10), 'csv')
        if os.environ.get('MOONRAY_PROBE_RENDER'):
            camera = scene.renderCamera
            camera.position.set((0.0, 3.5, 3.5))
            camera.rotation.set((-0.785, 0.0, 0.0))
            for key, value in (('resX', 480), ('resY', 270), ('first', 5), ('last', 5)):
                scene.renderItem.channel(key).set(value)
            lx.service.Selection().SetTime(5 / float(scene.fps))
            lx.eval('!render.animation {%s} openexr' % (out / 'csv'))
            from moonray_modo import scene_export
            scene_export.export({'path': out / 'csv.0005.rdla', 'format': 'rdla', 'outputs': True, 'collect': False, 'frames': False}, [])
            report['csv rendered'] = sorted(p.name for p in out.glob('csv*'))
            save()
except Exception:
    report['error'] = traceback.format_exc()
save()
