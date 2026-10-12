"""Native LPE parser validation in a disposable, one-pixel scalar scene."""
import re
from pathlib import Path
from .rdla import string


def prepare(directory, expressions):
    if not expressions or len(expressions)>128:
        raise ValueError('Choose between 1 and 128 light path expressions')
    directory=Path(directory)
    lines=['local camera=PerspectiveCamera("/check/camera") {}',
           'local layer=Layer("/check/layer") {}',
           'SceneVariables { ["camera"]=camera, ["layer"]=layer, ["image_width"]=1, ["image_height"]=1, '
           '["pixel_samples"]=1, ["sampling_mode"]=0, ["two_stage_output"]=false, ["max_depth"]=1 }']
    for index, expression in enumerate(expressions):
        if not isinstance(expression,str) or not expression.strip() or len(expression)>4096:
            raise ValueError('Enter a light path expression of at most 4096 characters')
        lines.append('RenderOutput(%s) { ["result"]=8, ["lpe"]=%s, ["file_name"]=%s, ["channel_name"]="check" }' %
                     (string('/check/output/'+str(index)),string(expression),string(str(directory/('output%d.exr'%index)))))
    path=directory/'check.rdla';path.write_text('\n'.join(lines),encoding='utf-8')
    return path


def results(directory, count, exit_code, log):
    """Only report acceptance after normal completion and a produced output for each expression."""
    clean=re.sub(r'\x1b\[[0-9;]*m','',log)
    failed={int(match.group(1)):'MoonRay rejected this light path expression' for match in
            re.finditer(r'skipping active render output /check/output/(\d+): invalid light path expression',clean)}
    if exit_code:
        raise ValueError('Native validation failed (exit %s): %s' % (exit_code,clean[-1200:].strip()))
    for index in range(count):
        if index not in failed and not (Path(directory)/('output%d.exr'%index)).is_file():
            raise ValueError('MoonRay did not produce validation output %d: %s' % (index+1,clean[-1200:].strip()))
    return failed
