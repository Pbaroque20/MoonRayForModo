import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import primitive_attributes as attributes

class Item:
    def __init__(self,value):self.value=value
    def readTag(self,tag):return self.value
    def setTag(self,tag,value):self.value=value

class AttributeValidation(unittest.TestCase):
    def entry(self,kind,value):return [{'name':'test','type':kind,'value':value}]
    def test_boolean_text_keeps_its_meaning(self):
        for raw,want in [('false',False),('0',False),(' TRUE ',True),('1',True),(False,False),(1,True)]:
            self.assertEqual(attributes.checked(self.entry('bool',raw))[0]['value'],want)
    def test_nonfinite_scalar_and_vector_values_are_rejected(self):
        for value in (float('nan'),float('inf'),float('-inf')):
            for kind,raw in [('float',value),('int',value),('color',[0,value,1]),('vec2',[value,1])]:
                with self.subTest(kind=kind,value=value),self.assertRaises(ValueError):
                    attributes.checked(self.entry(kind,raw))
    def test_bad_boolean_and_fractional_integer_are_rejected(self):
        for kind,value in [('bool','nope'),('bool',2),('bool',[]),('int',1.5)]:
            with self.assertRaises(ValueError):attributes.checked(self.entry(kind,value))
    def test_malformed_containers_are_rejected(self):
        for raw in ({'name':'test'},'bad',[None],[{'name':'test','type':[]}],self.entry('vec3','123')):
            with self.assertRaises(ValueError):attributes.checked(raw)
    def test_bad_saved_attribute_does_not_break_capture(self):
        item=Item(json.dumps(self.entry('int',float('inf'))))
        self.assertEqual(attributes.read(item),[])
    def test_invalid_write_leaves_existing_tag_untouched(self):
        item=Item('previous')
        with self.assertRaises(ValueError):attributes.write(item,self.entry('float',float('nan')))
        self.assertEqual(item.value,'previous')
    def test_export_rejects_invalid_values_before_writing_lines(self):
        lines=['existing']
        with self.assertRaises(ValueError):attributes.emit('/test',[self.entry('float',float('nan'))],lines)
        self.assertEqual(lines,['existing'])
    def test_valid_attributes_roundtrip(self):
        item=Item('')
        values=[{'name':kind,'type':kind,'value':value} for kind,value in
                [('float',-2.5),('int',12),('bool',False),('color',[8,1,0]),('vec2',[.2,.4]),('vec3',[1,2,3]),('string','hello')]]
        attributes.write(item,values)
        self.assertEqual(attributes.read(item),values)
        lines=[];self.assertEqual(len(attributes.emit('/test',[values],lines)),7)
        self.assertIn('false','\n'.join(lines))
