#!/usr/bin/env python
# -*- coding: utf-8 -*-
import csv
import codecs
import pprint
import re
import xml.etree.cElementTree as ET

import cerberus

from collections import defaultdict
from transliterate.decorators import transliterate_function
import unicodedata
from transliterate import translit, get_available_language_codes

OSM_PATH = "Tbilisi.osm"

NODES_PATH = "nodes.csv"
NODE_TAGS_PATH = "nodes_tags.csv"
WAYS_PATH = "ways.csv"
WAY_NODES_PATH = "ways_nodes.csv"
WAY_TAGS_PATH = "ways_tags.csv"

LOWER_COLON = re.compile(r'^([a-z]|_)+:([a-z]|_)+')
PROBLEMCHARS = re.compile(r'[=\+/&<>;\'"\?%#$@\,\. \t\r\n]')

# define schema ---------------------
import schema
SCHEMA  = {
    'node': {
        'type': 'dict',
        'schema': {
            'id': {'required': True, 'type': 'integer', 'coerce': int},
            'lat': {'required': True, 'type': 'float', 'coerce': float},
            'lon': {'required': True, 'type': 'float', 'coerce': float},
            'user': {'required': True, 'type': 'string'},
            'uid': {'required': True, 'type': 'integer', 'coerce': int},
            'version': {'required': True, 'type': 'string'},
            'changeset': {'required': True, 'type': 'integer', 'coerce': int},
            'timestamp': {'required': True, 'type': 'string'}
        }
    },
    'node_tags': {
        'type': 'list',
        'schema': {
            'type': 'dict',
            'schema': {
                'id': {'required': True, 'type': 'integer', 'coerce': int},
                'key': {'required': True, 'type': 'string'},
                'value': {'required': True, 'type': 'string'},
                'type': {'required': True, 'type': 'string'}
            }
        }
    },
    'way': {
        'type': 'dict',
        'schema': {
            'id': {'required': True, 'type': 'integer', 'coerce': int},
            'user': {'required': True, 'type': 'string'},
            'uid': {'required': True, 'type': 'integer', 'coerce': int},
            'version': {'required': True, 'type': 'string'},
            'changeset': {'required': True, 'type': 'integer', 'coerce': int},
            'timestamp': {'required': True, 'type': 'string'}
        }
    },
    'way_nodes': {
        'type': 'list',
        'schema': {
            'type': 'dict',
            'schema': {
                'id': {'required': True, 'type': 'integer', 'coerce': int},
                'node_id': {'required': True, 'type': 'integer', 'coerce': int},
                'position': {'required': True, 'type': 'integer', 'coerce': int}
            }
        }
    },
    'way_tags': {
        'type': 'list',
        'schema': {
            'type': 'dict',
            'schema': {
                'id': {'required': True, 'type': 'integer', 'coerce': int},
                'key': {'required': True, 'type': 'string'},
                'value': {'required': True, 'type': 'string'},
                'type': {'required': True, 'type': 'string'}
            }
        }
    }
}

# -----------------

#------------------------------------------#
#  make consistency in street abriviations #
#------------------------------------------#
street_type_re = re.compile(r'\b\S+\.?$', re.IGNORECASE)

expected = ["Street", "Avenue", "Boulevard", "Drive", "Court", "Place", "Square", "Lane", "Road", 
            "Trail", "Parkway", "Commons"]

# UPDATE THIS VARIABLE
mapping = { "St": "Street",
            "St.": "Street",
            "st.": "Street",
            "st": "Street",
            "street": "Street",
            "str.": "Street",
            "str": "Street",
            "Str.": "Street",
            "Str.": "Street",
            "M/R": "District",
            "m/r": "District",
            ")": "",
            "Str": "Street",
            "Str.": "Street",
            "ave": "Avenue",
            "ave.": "Avenue",
            "Ave": "Avenue",
            "Ave.": "Avenue",
            "avenue": "Avenue",
            "Rd.": "Road",
            "Rd": "Road"
            }

def audit_street_type(street_types, street_name):
   
    m = street_type_re.search(street_name)
    if m:
        street_type = m.group()
        if street_type not in expected:
            street_types[street_type].add(street_name)

def update_name(name, mapping):

    m = street_type_re.search(name)
    if m:
        street_type = m.group()
 
        if street_type in mapping.keys():
            #print 'Before: ' , name
            name = re.sub(m.group(), mapping[m.group()], name)
            #print 'After: ', name
                              
    return name
   


def clean_street_names(name):
    
    street_types = defaultdict(set)
    audit_street_type(street_types, name)
    better_name = update_name(name, mapping)
          
    return better_name
#------------------------------------------#

#------------------------------------------#
#  clean postcodes from unreal numbers    #
#------------------------------------------#
def clean_postcode(code):
  
    if len(code)!=4:
        code = 'unknown'
    
    return code
#------------------------------------------#

#-----------------------------------------------#
#  clean citynames from Incomprehensible values #
#-----------------------------------------------#
def clean_cityname(name):
    
    if 'Tbi' in name or 'tbi' in name:
        name='Tbilisi'
    elif name.isdigit(): #if only digits instead of name relpace it with unknown
        name = 'Unknown'
    elif 'Martkopi' in name or 'Zemo' in name: # after Tbilisi the most common 
        return name
    else:
        for char in name:
             if translit(char, 'ka') in name:
                    temp_name=name.replace(char,translit(char, "ka", reversed=True)) # Replace Georgian characters with Latin
                    if 'bili' in name:
                        name ='Tbilisi'
                    else:
                        name = temp_name
    
        
    return name
#-----------------------------------------------#

# Make sure the fields order in the csvs matches the column order in the sql table schema
NODE_FIELDS = ['id', 'lat', 'lon', 'user', 'uid', 'version', 'changeset', 'timestamp']
NODE_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_FIELDS = ['id', 'user', 'uid', 'version', 'changeset', 'timestamp']
WAY_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_NODES_FIELDS = ['id', 'node_id', 'position']


def shape_element(element, node_attr_fields=NODE_FIELDS, way_attr_fields=WAY_FIELDS,
                  problem_chars=PROBLEMCHARS, default_tag_type='regular'):
    """Clean and shape node or way XML element to Python dict"""

    node_attribs = {}
    way_attribs = {}
    way_nodes = []
    tags = []  # Handle secondary tags the same way for both node and way elements

    if element.tag == 'node':
        if all(field in element.attrib.keys() for field in node_attr_fields): # ensure that all fields required for the table are in the node 
            for field in node_attr_fields:
                node_attribs[field] = element.attrib[field]

            for stag in element.iterfind('./tag'):
                tags_data = {}
                # make consistency in street names----
                if stag.attrib['k'] == 'addr:street' or stag.attrib['k'] == 'name:en' or stag.attrib['k'] == 'name':
                    tags_data['value'] = clean_street_names(stag.attrib['v']) # make consistency in street names
                #-------------------------------------
                #print tags_data['value']
                # Update poste codes----
                elif stag.attrib['k'] == 'addr:postcode':
                    tags_data['value'] = clean_postcode(stag.attrib['v'])
                #-----------------------
                # Update city names codes----
                elif 'city' in stag.attrib['k']:   
                    tags_data['value'] = clean_cityname(stag.attrib['v'])
                #-----------------------------
                else:
                    tags_data['value'] = stag.attrib['v']
                if problem_chars.search(stag.attrib['k']) == None:
                    tags_data['id'] = element.attrib['id']
                    #tags_data['value'] = stag.attrib['v']

                    if LOWER_COLON.search(stag.attrib['k']) != None:
                        tags_data['key'] = stag.attrib['k'].split(":",1)[1]
                        tags_data['type'] = stag.attrib['k'].split(":",1)[0]

                    else:
                        tags_data['key'] = stag.attrib['k']
                        tags_data['type'] = 'regular'

                    tags.append(tags_data)

        if node_attribs:
           return {'node': node_attribs, 'node_tags': tags}
        else:
            return None
        
    elif element.tag == 'way':
        if all(field in element.attrib.keys() for field in way_attr_fields): # ensure that all fields required for the table are in the node 
            for field in way_attr_fields:
                way_attribs[field] = element.attrib[field]

            for stag in element.iterfind('./tag'):
                tags_data = {}
                tags_data = {}
                # make consistency in street names----
                if stag.attrib['k'] == 'addr:street' or stag.attrib['k'] == 'name:en' or stag.attrib['k'] == 'name':
                    tags_data['value'] = clean_street_names(stag.attrib['v']) # make consistency in street names
                #-------------------------------------
                #print tags_data['value']
                # Update poste codes----
                elif stag.attrib['k'] == 'addr:postcode':
                    tags_data['value'] = clean_postcode(stag.attrib['v'])
                #-----------------------
                # Update city names codes----
                elif 'city' in stag.attrib['k']:   
                    tags_data['value'] = clean_cityname(stag.attrib['v'])
                #-----------------------------
                else:
                    tags_data['value'] = stag.attrib['v']
                if problem_chars.search(stag.attrib['k']) == None:
                    tags_data['id'] = element.attrib['id']
                    #tags_data['value'] = stag.attrib['v']

                    if LOWER_COLON.search(stag.attrib['k']) != None:
                        tags_data['key'] = stag.attrib['k'].split(":",1)[1]
                        tags_data['type'] = stag.attrib['k'].split(":",1)[0]

                    else:
                        tags_data['key'] = stag.attrib['k']
                        tags_data['type'] = 'regular'

                    tags.append(tags_data)
            i=0
            for way_nd_value in element.iter('nd'):
                way_nodes.append({'id':element.attrib['id'],'node_id':way_nd_value.attrib['ref'],'position':i})
                i +=1

        if way_attribs:
            #print {'way': way_attribs, 'way_nodes': way_nodes, 'way_tags': tags}
            return {'way': way_attribs, 'way_nodes': way_nodes, 'way_tags': tags}
        else:
            return None
        


# ================================================== #
#               Helper Functions                     #
# ================================================== #
def get_element(osm_file, tags=('node', 'way', 'relation')):
    """Yield element if it is the right type of tag"""

    context = ET.iterparse(osm_file, events=('start', 'end'))
    _, root = next(context)
    for event, elem in context:
        if event == 'end' and elem.tag in tags:
            yield elem
            root.clear()


def validate_element(element, validator, schema=SCHEMA):
    """Raise ValidationError if element does not match schema"""
    if validator.validate(element, schema) is not True:
        field, errors = next(validator.errors.iteritems())
        message_string = "\nElement of type '{0}' has the following errors:\n{1}"
        error_string = pprint.pformat(errors)
        
        raise Exception(message_string.format(field, error_string))
        
class UnicodeDictWriter(csv.DictWriter, object):
    """Extend csv.DictWriter to handle Unicode input"""

    def writerow(self, row):
        super(UnicodeDictWriter, self).writerow({
            k: (v.encode('utf-8') if isinstance(v, unicode) else v) for k, v in row.iteritems()
        })

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


# ================================================== #
#               Main Function                        #
# ================================================== #
def process_map(file_in, validate):
    """Iteratively process each XML element and write to csv(s)"""

    with codecs.open(NODES_PATH, 'w') as nodes_file, \
         codecs.open(NODE_TAGS_PATH, 'w') as nodes_tags_file, \
         codecs.open(WAYS_PATH, 'w') as ways_file, \
         codecs.open(WAY_NODES_PATH, 'w') as way_nodes_file, \
         codecs.open(WAY_TAGS_PATH, 'w') as way_tags_file:

        nodes_writer = UnicodeDictWriter(nodes_file, NODE_FIELDS)
        node_tags_writer = UnicodeDictWriter(nodes_tags_file, NODE_TAGS_FIELDS)
        ways_writer = UnicodeDictWriter(ways_file, WAY_FIELDS)
        way_nodes_writer = UnicodeDictWriter(way_nodes_file, WAY_NODES_FIELDS)
        way_tags_writer = UnicodeDictWriter(way_tags_file, WAY_TAGS_FIELDS)

        nodes_writer.writeheader()
        node_tags_writer.writeheader()
        ways_writer.writeheader()
        way_nodes_writer.writeheader()
        way_tags_writer.writeheader()

        validator = cerberus.Validator()

        for element in get_element(file_in, tags=('node', 'way')):
            el = shape_element(element)
            if el:
                if validate is True:
                    validate_element(el, validator)

                if element.tag == 'node':
                    nodes_writer.writerow(el['node'])
                    node_tags_writer.writerows(el['node_tags'])
                elif element.tag == 'way':
                    ways_writer.writerow(el['way'])
                    way_nodes_writer.writerows(el['way_nodes'])
                    way_tags_writer.writerows(el['way_tags'])


if __name__ == '__main__':
    
    process_map(OSM_PATH, validate=True)
