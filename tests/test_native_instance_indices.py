import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('instance_indices',Path(__file__).resolve().parents[1]/'tools/port_instance_indices.py')
patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
class InstanceIndexPatch(unittest.TestCase):
 def test_adds_lower_bound_before_reference_access(self):
  source='int index = applyIndex ? indices[i] : 0;\nif (index > maxIndex) { index = 0; }\nif (!ref[index]) { continue; }'
  changed=patch.patch_text(source)
  self.assertIn('if (index < 0 || index > maxIndex) { index = 0; }',changed)
  self.assertEqual(changed.count('ref[index]'),1)
 def test_reapplication_is_stable(self):
  once=patch.patch_text(patch.OLD)
  self.assertEqual(patch.patch_text(once),once)
 def test_unrecognized_source_fails_closed(self):
  for source in ('different source',patch.OLD+' '+patch.OLD):
   with self.assertRaises(RuntimeError):patch.patch_text(source)
