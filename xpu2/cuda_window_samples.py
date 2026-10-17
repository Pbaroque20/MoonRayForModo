"""Version-2 CUDA boundary expectations from native records, not a Python RNG."""
import struct
from .cuda_samples import checksum
from .window_samples import read


def packet(words):
    data = struct.pack('<15I', *words)
    return data + struct.pack('<I', checksum(data))


def records(reference, tables=True):
    rows = read(reference)[1:]
    output = []
    for row in rows:
        dims = row['dims']
        for offset, anchor in enumerate(row['anchors']):
            index = row['begin'] + offset
            for mode in ('baseline', 'index_only'):
                start = anchor if mode == 'baseline' else index
                words = [0x32555058, 2, dims, row['depth'], 0xffffffff, index, 0, 6,
                         row['depth'], (77<<16)|96, row['seed']%3, row['purpose'], 0, row['seed'], start]
                data = packet(words)
                values = row[mode][offset*dims:(offset+1)*dims] if tables else []
                if tables:
                    words[5] += 1
                    if index-start == 8:
                        words[14] = index
                output.append({'case':row['id'], 'mode':mode, 'sample':index, 'begin':row['begin'], 'dims':dims,
                               'input':data, 'length':64, 'output':packet(words),
                               'result':[0 if tables else 1,row['sequence_hash'],*(values+[0]*(3-len(values)))]})
    first = rows[0]
    base = [0x32555058,2,1,0,0xffffffff,1016,0,6,0,(77<<16)|96,0,0,0,0,1008]
    for field, value in ((3,1),(4,2048),(6,1),(5,999),(5,1048)):
        words=base[:];words[field]=value
        if field==5:
            words[14]=value
        data=packet(words)
        output.append({'case':'unsupported','sample':words[5],'dims':words[2],
                       'input':data,'length':64,'output':data,'result':[1,first['sequence_hash'],0,0,0]})
    for field, value in ((0,0),(1,1),(2,0),(2,4),(4,0),(5,0xffffffff-8),(6,2),(7,5),(14,1017),(14,1007)):
        words=base[:];words[field]=value
        data=packet(words)
        output.append({'case':'invalid','sample':words[5],'dims':0,'input':data,'length':64,
                       'output':data,'result':[2,0,0,0,0]})
    corrupt=bytearray(packet(base));corrupt[56]^=1
    for data,length in ((bytes(corrupt),64),(packet(base),63)):
        output.append({'case':'invalid','sample':1016,'dims':0,'input':data,'length':length,
                       'output':data,'result':[2,0,0,0,0]})
    return output


def continuation_cases(items):
    """Group baseline draws for actual returned-state GPU continuation."""
    cases = {}
    for item in items:
        if item.get('mode') == 'baseline':
            cases.setdefault(item['case'], []).append(item)
    if len(cases) != 324:
        raise ValueError('Incomplete continuation cases')
    for samples in cases.values():
        samples.sort(key=lambda r: r['sample'])
        if (samples[-1]['sample'] != 1047 or samples[0]['sample'] != samples[0]['begin']
                or len(samples) != 1048-samples[0]['begin']):
            raise ValueError('Incomplete continuation interval')
        for previous, current in zip(samples, samples[1:]):
            if previous['sample']+1 != current['sample'] or previous['output'] != current['input']:
                raise ValueError('Discontinuous native sampler state')
    return cases
