"""XPU2 and MoonLightIPR read the MoonRay Source Overrides as the kit's MoonRay does: on unless the variable is 0. A
moonray_xpu2.exe started by hand (moonray_xpu2 render, a farm) then renders as Modo does, and as its MoonRay fallback;
the kit sets every one to 1 or 0, so in Modo the preferences still decide."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XPU2 = ROOT / 'xpu2/interactive'
SWITCHES = ('TOON_TERMINATOR', 'TOON_ALBEDO', 'DENOISE_CLEAN_GUIDES', 'CRYPTO_VOLUMES', 'CRYPTO_ONCE', 'FOG_ALPHA',
            'CAMERA_LIGHT_LPE', 'MIRRORED_MESHES', 'SCALAR_EMISSION', 'DSO_SEARCH', 'USD_SPECULAR', 'OPAQUE_ALPHA',
            'TRANSMISSION_ROUGHNESS', 'AUTO_XPU')
VARIABLE = r'"MOONRAY_MODO_(%s)"' % '|'.join(SWITCHES)
# What reads a switch as on only when it is 1: v[0]=='1', value[0] == '1', [0]==49.
OLD = re.compile(r"\[0\]\s*==\s*(?:'1'|49)")
# What reads it as on unless 0, or as off only when 0 (a guide's "raw" under DENOISE_CLEAN_GUIDES=0).
NEW = re.compile(r"!\w+\s*\|\|\s*\w+\[0\]\s*!=\s*'0'|\w+\s*&&\s*\w+\[0\]\s*==\s*'0'")


def sources():
    for pattern in ('*.h', '*.cc', '*.cu'):
        yield from XPU2.glob(pattern)
    for pattern in ('*.cpp', '*.h', '*.cu'):
        yield from (ROOT / 'moonlightipr/src').rglob(pattern)


class Xpu2SwitchesOnByDefault(unittest.TestCase):
    def test_every_read_of_a_switch_is_on_unless_0(self):
        reads = {}
        for path in sources():
            text = path.read_text(encoding='utf-8', errors='replace')
            for m in re.finditer(r'getenv\(' + VARIABLE + r'\)', text):
                # The statements that read the value it gave.
                after = text[m.end():m.end() + 160]
                where = '%s:%d' % (path.relative_to(ROOT), text.count('\n', 0, m.start()) + 1)
                self.assertIsNone(OLD.search(after), where)
                self.assertIsNotNone(NEW.search(after), where)
                reads[where] = m.group(1)
            # Through the session's one reader, by name.
            for m in re.finditer(r'modoSourceOverride\(' + VARIABLE + r'\)', text):
                reads['%s:%d' % (path.relative_to(ROOT), text.count('\n', 0, m.start()) + 1)] = m.group(1)
        self.assertTrue({'OPAQUE_ALPHA', 'SCALAR_EMISSION', 'TOON_TERMINATOR', 'USD_SPECULAR', 'CRYPTO_VOLUMES',
                         'DENOISE_CLEAN_GUIDES'} <= set(reads.values()), reads)

    def test_the_session_reads_its_switches_through_one_reader(self):
        scene = (XPU2 / 'cpu_scene.h').read_text(encoding='utf-8')
        self.assertIn("inline bool modoSourceOverride(const char* name){const char* v=std::getenv(name);return !v||v[0]!='0';}",
                      scene)
        # The material and integrator switches (Plan::modoSwitches, MaterialFlags).
        self.assertIn('{auto on=[](const char* n){return modoSourceOverride(n);};', scene)
        for name in ('TOON_ALBEDO', 'FOG_ALPHA', 'CRYPTO_VOLUMES', 'CAMERA_LIGHT_LPE', 'MIRRORED_MESHES', 'TOON_TERMINATOR',
                     'TRANSMISSION_ROUGHNESS'):
            self.assertIn('on("MOONRAY_MODO_%s")' % name, scene)

    def test_the_geometry_cache_keys_a_switch_by_its_reading(self):
        scene = (XPU2 / 'cpu_scene.h').read_text(encoding='utf-8')
        # Unset and 1 are one tessellation; the kit's 1 and 0 keep the keys they had.
        self.assertIn('k.add(std::string(name)+"="+(modoSourceOverride(name)?"1":"0"));', scene)
        self.assertNotIn('(v?v:"")', scene)


if __name__ == '__main__':
    unittest.main()
