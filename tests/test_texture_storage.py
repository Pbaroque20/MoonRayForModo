"""Textures held smaller (the Grass scene's 8K maps went into XPU2's texture overflow mode at 4 GB): the kit makes a grey
image one channel (maketx --monochrome-detect, which MoonRay reads grey in all three, gray_to_rgb); XPU2 holds a float file
in half floats, rounded (tiles past their range in floats), a grey one in one channel, and a flat tile as its one value, its
cache slots each its tile's format's size."""
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo/python/moonray_modo'
XPU2 = ROOT / 'xpu2/interactive'


class Storage(unittest.TestCase):
    def test_the_kit_makes_grey_images_one_channel_and_converts_them_again(self):
        source = (KIT / 'textures.py').read_text(encoding='utf-8')
        self.assertIn("'--unpremult', '--monochrome-detect']", source)
        self.assertIn("'v5-monochrome'", source)

    def test_xpu2_reads_half_one_channel_flat_and_wide_pages(self):
        core = (XPU2 / 'texture_core.h').read_text(encoding='utf-8')
        for token in ('if(flatPage(page))', 'if(widePage(page))', 'if(format==3)', 'if(format==4)', 'if(format==5)', 'if(format==6)'):
            self.assertIn(token, core)

    def test_xpu2_holds_float_files_in_half_floats_unless_told_not_to(self):
        host = (XPU2 / 'host_texture.h').read_text(encoding='utf-8')
        self.assertIn('rounds=sourceFormat==2&&(format==3||format==6);', host)
        self.assertIn('XPU2_SESSION_FLOAT_TEXTURES', host)
        self.assertIn('const bool wide=p->rounds&&!fits;', host)

    def test_the_card_gives_each_format_slots_of_its_size_and_flat_tiles_none(self):
        card = (XPU2 / 'async_gpu.h').read_text(encoding='utf-8')
        self.assertIn('U32 kindOf(unsigned format)', card)
        self.assertIn('to = fine_.flatPool->pointer + size_t(tile) * 16;', card)
        device = (XPU2 / 'async_gpu.cu').read_text(encoding='utf-8')
        self.assertIn('*entry = reinterpret_cast<const surface::V3*>(u.address);', device)


if __name__ == '__main__':
    unittest.main()
