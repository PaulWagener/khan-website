# Based on http://appengine-cookbook.appspot.com/recipe/extended-jsonify-function-for-dbmodel,
# with modifications for flask and performance.

from flask import request
import simplejson
from google.appengine.ext import db
from datetime import datetime
import re

SIMPLE_TYPES = (int, long, float, bool, basestring)
def dumps(obj, camel_cased=False):
    if isinstance(obj, SIMPLE_TYPES):
        return obj
    elif obj == None:
        return None
    elif isinstance(obj, list):
        items = [];
        for item in obj:
            items.append(dumps(item))
        return items
    elif isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(obj, dict):
        properties = {}
        for key in obj:
            properties[key] = dumps(obj[key])
        return properties

    properties = dict();
    if isinstance(obj, db.Model):
        properties['kind'] = obj.kind()

    serialize_blacklist = []
    if hasattr(obj, "_serialize_blacklist"):
        serialize_blacklist = obj._serialize_blacklist

    serialize_list = dir(obj)
    if hasattr(obj, "_serialize_whitelist"):
        serialize_list = obj._serialize_whitelist

    for property in serialize_list:
        if is_visible_property(property, serialize_blacklist):
            try:
                value = obj.__getattribute__(property)
                valueClass = str(value.__class__)
                if is_visible_class_name(valueClass):
                    value = dumps(value)
                    if camel_cased:
                        properties[camel_casify(property)] = value
                    else:
                        properties[property] = value
            except:
                continue

    if len(properties) == 0:
        return str(obj)
    else:
        return properties

UNDERSCORE_RE = re.compile("_([a-z])")
def camel_case_replacer(match):
    """ converts "_[a-z]" to remove the underscore and uppercase the letter """
    return match.group(0)[1:].upper()

def camel_casify(str):
    return re.sub(UNDERSCORE_RE, camel_case_replacer, str)

def is_visible_property(property, serialize_blacklist):
    return property[0] != '_' and not property.startswith("INDEX_") and not property in serialize_blacklist

def is_visible_class_name(class_name):
    return not(
                ('function' in class_name) or 
                ('built' in class_name) or 
                ('method' in class_name) or
                ('db.Query' in class_name)
            )

class JSONModelEncoder(simplejson.JSONEncoder):
    def default(self, o):
        """jsonify default encoder"""
        return dumps(o)

class JSONModelEncoderCamelCased(simplejson.JSONEncoder):
    def default(self, o):
        """jsonify default encoder"""
        return dumps(o, camel_cased=True)

def jsonify(data, **kwargs):
    """jsonify data in a standard (human friendly) way. If a db.Model
    entity is passed in it will be encoded as a dict.
    """

    if request.values.get("casing") == "camel":
        encoder = JSONModelEncoderCamelCased
    else:
        encoder = JSONModelEncoder
    return simplejson.dumps(data,
                            skipkeys=True,
                            sort_keys=True,
                            ensure_ascii=False,
                            indent=4,
                            cls=encoder)

