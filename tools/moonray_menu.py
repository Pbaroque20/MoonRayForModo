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
# A divider goes above each of these: render setup and preview, per-scene settings, output,
# the viewport, materials, MoonRay items, about.
GROUPS = ('cmd moonray.page object', 'cmd moonray.page final', 'cmd moonray.dock', 'cmd moonray.material.assign',
          'sub MoonRayEntityMenu:sheet', 'cmd moonray.about')
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
    lines = text.split(eol)
    # Only within the menu's own sheet, which ends at its closing tag.
    start = next((i for i, line in enumerate(lines) if 'key="MoonRayForModoMenu:sheet"' in line), None)
    if start is None:
        return text
    end = closing(lines, start)
    lines[start:end] = [line for line in lines[start:end] if 'MoonRayMenu_divider' not in line]
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
