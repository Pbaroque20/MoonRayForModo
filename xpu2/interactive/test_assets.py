import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from asset_snapshot import freeze,verify,members

class Assets(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.scene=self.root/'input.rdlb';self.scene.write_bytes(b'canonical')
        self.helper=self.root/'helper.exe';self.helper.write_bytes(b'test-double')
        self.asset=self.root/'color.tx';self.asset.write_bytes(b'existing-mips-unchanged')
        self.values=['color.tx','color.tx']
    def tearDown(self):self.temp.cleanup()
    def native(self,helper,runtime,folder,mode,scene,*args):
        refs=[dict(object='/map'+str(i),attribute='texture',step=0,index=0,vector=False,value=v) for i,v in enumerate(self.values)]
        if mode=='rewrite':
            mapping=json.loads(args[0].read_text());args[1].write_bytes(b'frozen'+args[0].read_bytes())
            refs=[{**r,'value':r['replacement']} for r in mapping]
        return dict(references=refs,unclassified_strings=[],coverage='test double')
    def freeze(self,**kw):
        with patch('asset_snapshot.native',self.native):
            return freeze(self.scene,self.helper,self.root,self.root/'package',self.root,**kw)
    def test_copy_dedupe_and_independence(self):
        manifest=self.freeze();before=manifest.read_bytes();data=json.loads(before)
        self.assertEqual(len(data['contract']['files']),1)
        self.asset.write_bytes(b'changed');self.scene.write_bytes(b'changed')
        self.assertEqual(verify(manifest),self.root/'package/scene.rdlb')
        self.assertEqual(manifest.read_bytes(),before)
        packaged=next((self.root/'package/assets').rglob('*.tx'))
        self.assertEqual(packaged.read_bytes(),b'existing-mips-unchanged')
    def test_changed_or_added_file_is_rejected(self):
        manifest=self.freeze();asset=next((manifest.parent/'assets').rglob('*.tx'))
        original=asset.read_bytes();asset.write_bytes(b'bad')
        with self.assertRaises(ValueError):verify(manifest)
        asset.write_bytes(original);extra=asset.with_name('unexpected.tx');extra.write_bytes(b'extra')
        with self.assertRaises(ValueError):verify(manifest)
    def test_budget_failure_never_publishes(self):
        with self.assertRaises(ValueError):self.freeze(max_bytes=3)
        self.assertFalse((self.root/'package/manifest.json').exists())
    def test_missing_asset_never_publishes(self):
        self.values=['missing.tx']
        with self.assertRaises(FileNotFoundError):self.freeze()
        self.assertFalse((self.root/'package/manifest.json').exists())
    def test_udim_preserves_existing_members_and_token(self):
        self.values=['tile.<UDIM>.tx']
        for n in (1001,1002,1011):(self.root/f'tile.{n}.tx').write_bytes(str(n).encode())
        (self.root/'tile.0999.tx').write_bytes(b'not-a-udim')
        manifest=self.freeze();data=json.loads(manifest.read_text())['contract']
        self.assertEqual(len(data['files']),3)
        self.assertIn('<UDIM>',data['references'][0]['replacement'])
        verify(manifest)
    def test_expressions_rejected_instead_of_silently_expanded(self):
        for value in ('$HOME/map.tx','%USERPROFILE%/map.tx','foo.*.tx','foo.<FRAME>.tx'):
            with self.assertRaises(ValueError):members(value,self.root)
    def test_incomplete_rewrite_never_publishes(self):
        original=self.native
        def broken(*args):
            result=original(*args)
            if args[3]=='rewrite':result['references']=[]
            return result
        with patch('asset_snapshot.native',broken):
            with self.assertRaises(ValueError):freeze(self.scene,self.helper,self.root,self.root/'package',self.root)
        self.assertFalse((self.root/'package/manifest.json').exists())
    def test_no_overwrite(self):
        manifest=self.freeze();data=manifest.read_bytes()
        with self.assertRaises(FileExistsError):self.freeze()
        self.assertEqual(manifest.read_bytes(),data)
    def test_udim_member_budget_is_checked_during_discovery(self):
        for n in (1001,1002):(self.root/f'tile.{n}.tx').write_bytes(b'x')
        with self.assertRaises(ValueError):members('tile.<UDIM>.tx',self.root,1)
    def test_moved_package_requires_path_rewrite(self):
        manifest=self.freeze();moved=self.root/'moved'
        manifest.parent.rename(moved)
        with self.assertRaises(ValueError):verify(moved/'manifest.json')
if __name__=='__main__':unittest.main()
