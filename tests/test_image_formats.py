"""The picture types the plugin saves: what each holds, how the image tool is asked to write it, and how a file dialog
offers them."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import image_formats


class Types(unittest.TestCase):
    def test_the_standard_types_are_offered(self):
        extensions = {held[2] for held in image_formats.FORMATS}
        self.assertEqual(extensions, {'exr', 'png', 'jpg', 'tif', 'tga'})
        self.assertEqual([held[3] for held in image_formats.FORMATS if held[2] == 'png'], ['uint8', 'uint16'])
        self.assertEqual([held[3] for held in image_formats.FORMATS if held[2] == 'tif'], ['uint8', 'uint16', 'float'])

    def test_a_picture_to_look_at_goes_through_the_view_transform_and_numbers_do_not(self):
        shown = image_formats.arguments('png16', 'beauty', 'in.exr', 'out.png', {})
        self.assertEqual(shown[shown.index('-d') + 1], 'uint16')
        self.assertTrue(image_formats.linear('tif32'))
        values = image_formats.arguments('tif32', 'beauty', 'in.exr', 'out.tif')
        self.assertEqual(values[values.index('-d') + 1], 'float')
        self.assertEqual(image_formats.arguments('exr16', 'beauty', 'in.exr', 'out.exr'), ['in.exr', '-d', 'half', '-o', 'out.exr'])

    def test_a_jpeg_is_written_as_finely_as_asked(self):
        args = image_formats.arguments('jpg', 'beauty', 'in.exr', 'out.jpg', {}, quality=80)
        self.assertEqual(args[args.index('--compression') + 1], 'jpeg:80')

    def test_a_cryptomatte_is_openexr_at_full_precision_only(self):
        self.assertEqual(image_formats.arguments('exr16', 'cryptomatte', 'c.exr', 'o.exr')[1:3], ['-d', 'float'])
        with self.assertRaises(ValueError):
            image_formats.arguments('png8', 'cryptomatte', 'c.exr', 'o.png')

    def test_the_file_dialog_says_the_bits(self):
        filters, types = image_formats.picture_filters()
        self.assertEqual(types['OpenEXR (*.exr)'], 'exr32')
        self.assertEqual(types['PNG, 16-bit (*.png)'], 'png16')
        self.assertTrue(filters.startswith('OpenEXR (*.exr)'))
        self.assertEqual(image_formats.from_path('a/b.JPEG'), 'jpg')


if __name__ == '__main__':
    unittest.main()
