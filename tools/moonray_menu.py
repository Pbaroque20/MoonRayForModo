"""Keep the kit's MoonRay menu in order: the MoonRay items submenu, dividers between groups of
entries, and plain characters in what the menu and forms display.

The menu lives in layout.cfg beside forms this module does not touch, so it edits the text in
place rather than writing the file out again. tools/install_moonlight.py applies it to the
installed kit; run this file to apply it to the checkout.
"""
import re
import sys
from pathlib import Path

ENTRY = ('      <list type="Control" val="sub MoonRayEntityMenu:sheet"><atom type="Label">Add MoonRay Item</atom>'
         '<atom type="ShowLabel">1</atom><atom type="PopupFace">option</atom><atom type="Hash">MoonRayEntityMenu:sheet</atom></list>')
ABOUT = '      <list type="Control" val="cmd moonray.about">'
# The entries above the viewport one, in order. The preview window does each of them; render
# settings are the Render item's MoonRay properties.
ENTRIES = (('moonray.page preview', 'Open Preview', 'preview'), ('moonray.page settings', 'Render Settings', 'settings'),
           ('moonray.page preferences', 'Preview Preferences...', 'preferences'),
           ('moonray.page final', 'Render EXR...', 'final'), ('moonray.page animation', 'Render Animation...', 'animation'),
           ('moonray.page export', 'Export MoonRay Scene...', 'export'), ('moonray.page stop', 'Stop Rendering', 'stop'),
           ('moonray.page log', 'Render Log', 'log'),
           ('moonray.page objects', 'Light Links, Emitters and Volumes...', 'objects'),
           ('moonray.page outputs', 'Named Outputs...', 'outputs'),
           ('moonray.page colors', 'Color Spaces and Texture Cache...', 'colors'),
           ('moonray.page report', 'Report Scene Assets...', 'report'), ('moonray.page package', 'Package Render Scene...', 'package'),
           ('moonray.page package_sequence', 'Package Animation...', 'package_sequence'),
           ('moonray.assets.relink', 'Relink Missing Images...', 'relink'))
# A divider goes above each of these: render setup and preview, per-scene settings, output,
# the viewport, materials, MoonRay items, about.
GROUPS = ('cmd moonray.page final', 'cmd moonray.page objects', 'cmd moonray.page report', 'cmd moonray.dock',
          'cmd moonray.material.assign', 'sub MoonRayEntityMenu:sheet', 'cmd moonray.about')
DIVIDER = '      <list type="Control" val="div "><atom type="Hash">MoonRayMenu_divider%d:control</atom></list>'
# Modo's menu drew these as stray letters and bars.
PLAIN = (('…', '...'), ('—', '-'), ('–', '-'))


def closing(lines, start):
    """Where the sheet that opens at start closes: the first closing tag at its own indent."""
    indent = lines[start][:len(lines[start]) - len(lines[start].lstrip())]
    return next(i for i in range(start + 1, len(lines)) if lines[i].rstrip() == indent + '</hash>')


def tidy(text):
    """Return layout.cfg's text with the menu put in order; text that is already in order comes back unchanged."""
    eol = '\r\n' if '\r\n' in text else '\n'
    for odd, usual in PLAIN:
        text = text.replace(odd, usual)
    earlier = [line for line in text.splitlines() if 'MoonRayEntityMenu' in line]
    for line in earlier:
        if line != ENTRY:
            text = text.replace(line, ENTRY, 1)
    if not earlier and text.count(ABOUT) == 1:
        text = text.replace(ABOUT, ENTRY + eol + ABOUT)
    # The override layer is no longer offered; a material is added to a mesh or from Add Layer.
    lines = [line for line in text.split(eol) if 'val="cmd moonray.material.addMoonShineOverride"' not in line]
    # A MaterialX file is imported onto a mesh as a material of its own, not through an override layer.
    for index, line in enumerate(lines):
        if 'val="cmd moonray.material.nodeOverride"' in line and index + 1 < len(lines) and 'Add MaterialX Override' in lines[index + 1]:
            lines[index] = line.replace('moonray.material.nodeOverride', 'moonray.material.importMaterialX')
            lines[index + 1] = lines[index + 1].replace('Add MaterialX Override', 'Import MaterialX Material...')
    # Only within the menu's own sheet, which ends at its closing tag.
    start = next((i for i, line in enumerate(lines) if 'key="MoonRayForModoMenu:sheet"' in line), None)
    if start is None:
        return text
    end = closing(lines, start)
    lines[start:end] = [line for line in lines[start:end] if 'MoonRayMenu_divider' not in line]
    # Everything from the first entry to the viewport one is rebuilt from ENTRIES.
    first = next((i for i in range(start, closing(lines, start)) if '<list type="Control"' in lines[i]), None)
    dock = next((i for i in range(start, closing(lines, start)) if 'val="cmd moonray.dock"' in lines[i]), None)
    if first is not None and dock is not None and first <= dock:
        built = []
        for command, label, key in ENTRIES:
            built += ['      <list type="Control" val="cmd %s">' % command, '        <atom type="Label">%s</atom>' % label,
                      '        <atom type="Hash">MoonRayMenu_%s:control</atom>' % key, '      </list>']
        lines[first:dock] = built
    end = closing(lines, start)
    out, number = [], 0
    for index, line in enumerate(lines):
        if start < index < end and any(re.match(r'\s*<list type="Control" val="%s"' % re.escape(anchor), line) for anchor in GROUPS):
            out.append(DIVIDER % number)
            number += 1
        out.append(line)
    return eol.join(out)


if __name__ == '__main__':
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/layout.cfg'
    before = path.read_bytes().decode('utf-8')
    after = tidy(before)
    if after != before:
        path.write_bytes(after.encode('utf-8'))
    print('Menu in order:', path)


CURVE_ROWS = (
    ('curves', 'Render Curves as Tubes', 'Requires object overrides. Curves, splines and line polygons of this mesh render as round tubes, '
     'all of one material as a single curve geometry.'),
    ('curve_root_width', 'Curve Width at Root (mm)', 'The width of each strand where it starts.'),
    ('curve_tip_width', 'Curve Width at Tip (mm)', 'The width of each strand where it ends. Zero comes to a point.'),
    ('curve_envelope', 'Curve Envelope', 'How the width goes from root to tip along the length: 1 is an even taper, higher keeps the root '
     'width for longer, lower thins early.'),
    ('curve_samples', 'Samples per Curve Bend', 'How finely a spline is followed. Line polygons are used as they are.'),
    ('curve_uv', 'Curve UVs along Length', 'Gives each strand UVs for textures: V runs 0 at the root to 1 at the tip by length, U tells '
     'the strands apart.'))


HAIR_ROWS = (
    ('hair', 'Grow Hair from Curves', 'Requires object overrides. The curves of this mesh become guides: many strands are grown from each when the scene '
     'is rendered, and take the curve widths above.'),
    ('hair_scalp', 'Hair Scalp', 'The mesh the hair grows on. Every root is held to its surface, so no strand floats above it or starts inside it.'),
    ('hair_mode', 'Hair Grows', 'Around each guide: strands follow that guide and gather toward it, as locks. Between guides: each strand is '
     'shaped by the guides nearest it and fills the space between them, as fur.'),
    ('hair_count', 'Strands per Guide', 'How many strands are grown from each guide.'),
    ('hair_width', 'Cluster Width at Root (mm)', 'How far from its guide a strand may start.'),
    ('hair_clump', 'Cluster Closes toward Tip', 'Around each guide: 0 keeps the strands as far apart as at the root, 1 brings them to the guide at its tip.'),
    ('hair_length', 'Length Variation', 'How much shorter than its guide a strand may be: 0 for none, 0.3 for up to 30%.'),
    ('hair_seed', 'Hair Seed', 'Another number grows other hair from the same guides. The same number always grows the same hair.'),
    ('hair_guides', 'Render Guides Too', 'Render the guide curves themselves along with the hair grown from them.'))


def curve_controls(text):
    """The mesh form's curve controls, after the last of its subdivision controls; unchanged if they are there."""
    anchor = '<list type="Control" val="cmd moonray.object.adaptive_error ?">'
    if 'cmd moonray.object.curves ?' in text or text.count(anchor) != 1:
        return hair_controls(text)
    end = text.index('</list>', text.index(anchor)) + len('</list>')
    eol = '\r\n' if '\r\n' in text else '\n'
    rows = ''.join(eol + '      <list type="Control" val="cmd moonray.object.%s ?"><atom type="Label">%s</atom><atom type="Tooltip">%s</atom></list>' % row
                   for row in CURVE_ROWS)
    return hair_controls(text[:end] + rows + text[end:])


def hair_controls(text):
    """The mesh form's hair controls, after its curve controls; unchanged if they are there."""
    anchor = '<list type="Control" val="cmd moonray.object.curve_uv ?">'
    if 'cmd moonray.object.hair ?' in text or text.count(anchor) != 1:
        return text
    end = text.index('</list>', text.index(anchor)) + len('</list>')
    eol = '\r\n' if '\r\n' in text else '\n'
    rows = ''.join(eol + '      <list type="Control" val="cmd moonray.object.%s ?"><atom type="Label">%s</atom><atom type="Tooltip">%s</atom></list>' % row
                   for row in HAIR_ROWS)
    return text[:end] + rows + text[end:]
