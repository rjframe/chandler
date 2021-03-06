#   Copyright (c) 2003-2007 Open Source Applications Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.


from chandlerdb.item.c import CItem


class ItemWriter(object):

    def writeItem(self, item, version):

        status = item._status
        withSchema = (status & CItem.WITHSCHEMA) != 0
        deleted = (status & CItem.DELETED) != 0
        kind = item.itsKind
        size = 0

        size += self._kind(kind)
        if deleted:
            size += self._parent(None, False)
        else:
            parent = item.itsParent
            if parent is None:
                raise AssertionError, 'parent for %s is None' %(item._repr_())
            size += self._parent(parent, item._children is not None)
        size += self._name(item._name)

        itemClass = type(item)
        if withSchema or kind is None:
            size += self._className(itemClass.__module__, itemClass.__name__)
        elif not (kind.getItemClass() is itemClass or
                  kind._values._isTransient('classes')): # generated class
            size += self._className(itemClass.__module__, itemClass.__name__)
        else:
            size += self._className(None, None)

        if not deleted:
            all = ((status & (CItem.NEW | CItem.MERGED)) != 0 or
                   item.itsVersion == 0)
            size += self._values(item, version, withSchema, all)
            size += self._references(item, version, withSchema, all)
            size += self._children(item, version, all)
            size += self._acls(item, version, all)

        return size

    def writeList(self, buffer, item, version, value, withSchema, attrType):
        raise NotImplementedError, "%s.writeList" %(type(self))

    def writeSet(self, buffer, item, version, value, withSchema, attrType):
        raise NotImplementedError, "%s.writeSet" %(type(self))

    def writeDict(self, buffer, item, version, value, withSchema, attrType):
        raise NotImplementedError, "%s.writeDict" %(type(self))

    def _kind(self, kind):
        raise NotImplementedError, "%s._kind" %(type(self))

    def _parent(self, parent, isContainer):
        raise NotImplementedError, "%s._parent" %(type(self))

    def _name(self, name):
        raise NotImplementedError, "%s._name" %(type(self))

    def _className(self, moduleName, className):
        raise NotImplementedError, "%s._className" %(type(self))

    def _values(self, item, version, withSchema, all):
        raise NotImplementedError, "%s._values" %(type(self))

    def _value(self, item, name, value, version, flags, withSchema, attribute):
        raise NotImplementedError, "%s._value" %(type(self))

    def _unchangedValue(self, item, name):
        raise NotImplementedError, "%s._unchangedValue" %(type(self))

    def _references(self, item, version, withSchema, all):
        raise NotImplementedError, "%s._references" %(type(self))

    def _children(self, item, version, all):
        raise NotImplementedError, "%s._children" %(type(self))

    def _acls(self, item, version, all):
        raise NotImplementedError, "%s._acls" %(type(self))


class XMLItemWriter(ItemWriter):

    def __init__(self, generator):

        self.generator = generator

    def writeItem(self, item, version):

        attrs = {}
        attrs['uuid'] = item.itsUUID.str16()
        attrs['version'] = str(version)
        if item._isWithSchema():
            attrs['withSchema'] = 'True'
        if item._isCoreSchema():
            attrs['coreSchema'] = 'True'

        self.generator.startElement('item', attrs)
        super(XMLItemWriter, self).writeItem(item, version)
        self.generator.endElement('item')

        return 0

    def _name(self, name):

        if name is not None:
            self.generator.startElement('name', {})
            self.generator.characters(name)
            self.generator.endElement('name')

        return 0
        
    def _kind(self, kind):

        if kind is not None:
            self.generator.startElement('kind', { 'type': 'path' })
            self.generator.characters(str(kind.itsPath))
            self.generator.endElement('kind')

        return 0

    def _className(self, moduleName, className):

        if moduleName is not None and className is not None:
            self.generator.startElement('class', { 'module': moduleName })
            self.generator.characters(className)
            self.generator.endElement('class')

        return 0
        
    def _parent(self, parent, isContainer):

        attrs = {}
        if isContainer:
            attrs['container'] = 'True'

        self.generator.startElement('parent', attrs)
        self.generator.characters(parent.itsUUID.str16())
        self.generator.endElement('parent')

        return 0

    def _values(self, item, version, withSchema, all):
        return item._values._xmlValues(self.generator, withSchema, version)

    def _references(self, item, version, withSchema, all):
        return item._references._xmlValues(self.generator, withSchema, version)

    def _children(self, item, version, all):
        return 0

    def _acls(self, item, version, all):
        return 0


class ItemReader(object):

    def readItem(self, view, afterLoadHooks):
        raise NotImplementedError, "%s.readItem" %(type(self))

    def _kind(self, spec, withSchema, view, afterLoadHooks):
        return view._findSchema(spec, withSchema)

    def _parent(self, spec, withSchema, view, afterLoadHooks):
        return view.find(spec)

    def _class(self, moduleName, className, withSchema, kind,
               view, afterLoadHooks):

        if className is None:
            if kind is None:
                return view.classLoader.getItemClass()
            else:
                return kind.getItemClass()
        else:
            return view.classLoader.loadClass(className, moduleName)

    def getUUID(self):
        raise NotImplementedError, "%s.getUUID" %(type(self))

    def getVersion(self):
        raise NotImplementedError, "%s.getVersion" %(type(self))

    def isDeleted(self):
        raise NotImplementedError, "%s.isDeleted" %(type(self))


class ItemPurger(object):

    def purgeItem(self, uuid, version):
        raise NotImplementedError, "%s.purgeItem" %(type(self))


class ValueReader(object):

    def readValue(self, view, uValue):
        raise NotImplementedError, "%s.readValue" %(type(self))
