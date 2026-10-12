"""Guard both bounds of native instancer reference indices before array access."""
from pathlib import Path

OLD = "if (index > maxIndex) {"
NEW = "if (index < 0 || index > maxIndex) {"

def patch_text(text):
    if NEW in text:
        return text
    if text.count(OLD) != 1:
        raise RuntimeError('Native instance index patch anchor missing or ambiguous')
    return text.replace(OLD, NEW, 1)

def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'upstream/openmoonray/moonray/moonray/lib/rendering/geom/InstanceProceduralLeaf.cc'
    text = source.read_text(encoding='utf-8')
    patched = patch_text(text)
    if patched != text:
        source.write_text(patched, encoding='utf-8')

if __name__ == '__main__':
    main()
