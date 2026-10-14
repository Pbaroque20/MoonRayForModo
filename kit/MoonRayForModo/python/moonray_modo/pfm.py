"""PFM pictures as the loaded MoonRay hands them over when they are too large to hand over in memory.

MoonRay writes such a picture's rows top first, in the order it hands a smaller picture over in memory. A PFM file is
read bottom row first (OpenImageIO, which shows it, reads it so), so a picture handed over that way came out upside
down: at 3840 x 2160, for one, and not at smaller sizes. upright() puts the rows in the order the file is read in."""


def header(data):
    """The PFM's channels, width, height and where its pixels begin; ValueError for anything else."""
    parts, at = [], 0
    while len(parts) < 4:
        while at < len(data) and data[at:at + 1].isspace():
            at += 1
        start = at
        while at < len(data) and not data[at:at + 1].isspace():
            at += 1
        if start == at:
            raise ValueError('Not a PFM picture')
        parts.append(data[start:at])
    kind, width, height = parts[0], int(parts[1]), int(parts[2])
    float(parts[3])
    if kind not in (b'PF', b'Pf') or width <= 0 or height <= 0:
        raise ValueError('Not a PFM picture')
    return (3 if kind == b'PF' else 1), width, height, at + 1


def upright(path):
    """Rewrite a PFM written top row first so that it is read the right way up."""
    with open(path, 'rb') as stream:
        data = stream.read()
    channels, width, height, start = header(data)
    row = width * channels * 4
    if len(data) - start != row * height:
        raise ValueError('PFM picture of the wrong size')
    rows = [data[start + row * y:start + row * (y + 1)] for y in range(height - 1, -1, -1)]
    with open(path, 'wb') as stream:
        stream.write(data[:start])
        stream.write(b''.join(rows))
