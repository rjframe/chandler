
__revision__  = "$Revision$"
__date__      = "$Date$"
__copyright__ = "Copyright (c) 2002 Open Source Applications Foundation"
__license__   = "http://osafoundation.org/Chandler_0.1_license_terms.htm"

import repository.item as ItemPackage

from repository.util.UUID import UUID
from repository.util.Path import Path
from repository.util.LinkedMap import LinkedMap
from repository.item.Indexes import NumericIndex

class ItemRef(object):
    'A wrapper around a bi-directional link between two items.'
    
    def __init__(self, item, name, other, otherName,
                 otherCard=None, otherPersist=None, otherAlias=None):

        super(ItemRef, self).__init__()
        self.attach(item, name, other, otherName,
                    otherCard, otherPersist, otherAlias)

    def _copy(self, references, item, copyItem, name, policy, copies):

        if policy == 'copy':
            references[name] = ItemRef(copyItem, name, self.other(item),
                                       copyItem._kind.getOtherName(name))

        elif policy == 'cascade':
            other = self.other(item)
            copyOther = copies.get(other.itsUUID, None)

            if copyOther is None:
                if item.itsParent is copyItem.itsParent:
                    otherParent = other.itsParent
                else:
                    otherParent = copyItem.itsParent
                copyOther = other.copy(None, otherParent, copies)

            if not name in references:
                references[name] = ItemRef(copyItem, name, copyOther,
                                           copyItem._kind.getOtherName(name))

    def __repr__(self):

        return '<ItemRef: %s - %s>' %(self._item, self._other)

    def _setItem(self, item):
        pass

    def getItem(self):
        'Return the item this link was established from.'
        
        item = self._item._loadItem()

        if item is not None:
            self._item = item
            return item

        raise DanglingRefError, '%s <-> %s' %(self._item, self._other)

    def getOther(self):
        'Return the opposite item this link was established from.'

        other = self._other._loadItem()

        if other is not None:
            self._other = other
            return other

        raise DanglingRefError, '%s <-> %s' %(self._item, self._other)

    def attach(self, item, name, other, otherName,
               otherCard=None, otherPersist=None, otherAlias=None):

        assert item is not None, 'item is None'
        assert other is not None, 'other is None'

        self._item = item
        self._other = other

        if not isinstance(other, Stub):
            if other.hasAttributeValue(otherName):
                old = other.getAttributeValue(otherName)
                if isinstance(old, RefDict):
                    old.__setitem__(item._uuid, self, alias=otherAlias)
                    return
            else:
                if otherCard is None:
                    otherCard = other.getAttributeAspect(otherName,
                                                         'cardinality',
                                                         default='single')
                if otherCard != 'single':
                    old = other._refDict(otherName, name, otherPersist)
                    other._references[otherName] = old
                    old.__setitem__(item._uuid, self, alias=otherAlias)
                    return
            
            other.setAttributeValue(otherName, self,
                                    _attrDict=other._references)

    def detach(self, item, name, other, otherName):

        old = other.getAttributeValue(otherName, _attrDict=other._references)

        if isinstance(old, RefDict):
            old._removeRef(item._uuid)
        else:
            other._removeRef(otherName)

        other.setDirty(attribute=otherName, dirty=item.RDIRTY)

    def reattach(self, item, name, old, new, otherName):

        self.detach(item, name, old, otherName)
        self.attach(item, name, new, otherName)

    def _unload(self, item):

        # using direct compares instead of accessors to avoid re-loading
        
        if item is self._item:
            if self._other._isItem():
                self._item = UUIDStub(self._other, item)
        elif item is self._other:
            if self._item._isItem():
                self._other = UUIDStub(self._item, item)
        else:
            raise ValueError, "%s doesn't reference %s" %(self, item)

    def other(self, item):
        'Return the other end of the ref relative to item.'

        if self.getItem() is item:
            return self.getOther()
        elif self.getOther() is item:
            return self.getItem()
        else:
            raise ValueError, "%s doesn't reference %s" %(self, item)

    def check(self, item, name):

        logger = item.itsView.logger
        
        try:
            other = self.other(item)
        except DanglingRefError, e:
            logger.error('DanglingRefError: %s', e)
            return False
        except ValueError, e:
            logger.error('ValueError: %s', e)
            return False
        else:
            if other.isStale():
                logger.error('Found stale item %s at %s of kind %s',
                             other, other.itsPath,
                             other._kind.itsPath)
                return False
            else:
                otherName = item._kind.getOtherName(name, default=None)
                if otherName is None:
                    logger.error('otherName is None for attribute %s.%s',
                                 item._kind.itsPath, name)
                    return False
                otherOtherName = other._kind.getOtherName(otherName,
                                                          default=None)
                if otherOtherName != name:
                    logger.error("otherName for attribute %s.%s, %s, does not match otherName for attribute %s.%s, %s",
                                 item._kind.itsPath, name, otherName,
                                 other._kind.itsPath, otherName,
                                 otherOtherName)
                    return False

        return True

    def _refCount(self):

        return 1

    def _xmlValue(self, name, item, generator, withSchema, version, flags,
                  mode, previous=None, next=None, alias=None):

        def addAttr(attrs, attr, value):

            if value is not None:
                if isinstance(value, UUID):
                    attrs[attr + 'Type'] = 'uuid'
                    attrs[attr] = value.str64()
                elif isinstance(attr, str) or isinstance(attr, unicode):
                    attrs[attr] = value.encode('utf-8')
                else:
                    raise NotImplementedError, "%s, type: %s" %(value,
                                                                type(value))

        other = self.other(item)
        attrs = { 'type': 'uuid' }

        addAttr(attrs, 'name', name)
        addAttr(attrs, 'previous', previous)
        addAttr(attrs, 'next', next)
        addAttr(attrs, 'alias', alias)

        if flags:
            attrs['flags'] = str(flags)

        if withSchema:
            attrs['otherName'] = item._kind.getOtherName(name)

        generator.startElement('ref', attrs)
        generator.characters(other._uuid.str64())
        generator.endElement('ref')


class _noneRef(ItemRef):

    def __init__(self):
        super(_noneRef, self).__init__(None, None, None, None)

    def __repr__(self):
        return '<NoneRef>'

    def _copy(self, references, item, copyItem, name, policy, copies):
        return self

    def attach(self, item, name, other, otherName,
               otherCard=None, otherPersist=None, otherAlias=None):
        pass

    def detach(self, item, name, other, otherName):
        pass
    
    def reattach(self, item, name, old, new, otherName):
        item.name = ItemRef(item, name, new, otherName)
    
    def getItem(self):
        return None

    def getOther(self):
        return None

    def _unload(self, item):
        pass

    def other(self, item):
        return None

    def check(self, item, name):
        return True

    def _refCount(self):
        return 0

    def _xmlValue(self, name, item, generator, withSchema, version, flags,
                  mode, previous=None, next=None, alias=None):

        attrs = { 'name': name, 'type': 'none' }
        if flags:
            attrs['flags'] = str(flags)
        generator.startElement('ref', attrs)
        generator.endElement('ref')

    def __new__(cls, *args, **kwds):

        try:
            return _noneRef._noneRef
        except AttributeError:
            _noneRef._noneRef = ItemRef.__new__(cls, *args, **kwds)
            return _noneRef._noneRef

    def __nonzero__(self):
        return False
    
NoneRef = _noneRef()


class Stub(object):
    pass


class ItemStub(Stub):
    
    def __init__(self, item, args):

        super(ItemStub, self).__init__()

        self.item = item
        self.args = args

    def __repr__(self):

        return '<ItemStub: %s>' %(self.args.spec)

    def _loadItem(self):

        other = self.item.find(self.args.spec)
        if other is not None:
            self.args._attach(self.item, other)

        return other

    def _isItem(self):

        return False


class UUIDStub(Stub):

    def __init__(self, item, other):

        super(UUIDStub, self).__init__()

        self.item = item
        self.uuid = other._uuid

    def __repr__(self):

        return '<UUIDStub: %s>' %(self.uuid)

    def _loadItem(self):

        other = self.item.find(self.uuid)
        if other is None:
            raise DanglingRefError, '%s <-> %s' %(self.item, self.uuid)

        return other
    
    def _isItem(self):

        return False
    

class RefArgs(object):
    'A wrapper around arguments necessary to make and store an ItemRef'
    
    def __init__(self, attrName, refName, spec, otherName, otherCard,
                 valueDict, previous=None, next=None, alias=None):

        super(RefArgs, self).__init__()
        
        self.attrName = attrName
        self.refName = refName
        self.spec = spec
        self.otherName = otherName
        self.otherCard = otherCard
        self.valueDict = valueDict
        self.previous = previous
        self.next = next
        self.alias = alias
        self.ref = None
        
    def attach(self, item, repository):

        if isinstance(self.spec, UUID):
            other = repository.find(self.spec, load=False)
        else:
            other = item.find(self.spec, load=False)
            
        if self.refName is None:
            if other is None:
                raise ValueError, "refName to %s is unspecified, %s should be loaded before %s" %(self.spec, self.spec, item.itsPath)
            else:
                self.refName = other._uuid

        if other is not None:
            if not other._isAttaching():
                try:
                    item._setAttaching()
                    return self._attach(item, other)
                finally:
                    item._setAttaching(False)
        else:
            self.ref = ItemRef(item, self.attrName,
                               ItemStub(item, self), self.otherName,
                               self.otherCard)
            repository._addStub(self.ref)
            self.valueDict.__setitem__(self.refName, self.ref, 
                                       self.previous, self.next, self.alias,
                                       False)

        return None

    def _attach(self, item, other):
        
        value = other._references.get(self.otherName)
        
        if value is None or value is NoneRef:
            if self.ref is not None:
                self.ref.attach(item, self.attrName,
                                other, self.otherName, self.otherCard)
            else:
                value = ItemRef(item, self.attrName,
                                other, self.otherName, self.otherCard)
                self.valueDict.__setitem__(self.refName, value,
                                           self.previous, self.next,
                                           self.alias, False)

        elif isinstance(value, ItemRef):
            if isinstance(value._other, Stub):
                value._other = item
                self.valueDict.__setitem__(self.refName, value,
                                           self.previous, self.next,
                                           self.alias, False)

            elif isinstance(value._item, Stub):
                value._item = item
                self.valueDict.__setitem__(self.refName, value,
                                           self.previous, self.next,
                                           self.alias, False)
            else:
                return value

        elif isinstance(value, RefDict):
            otherRefName = item._uuid
            if value.has_key(otherRefName):
                value = value._getRef(otherRefName)
                if isinstance(value._other, Stub):
                    value._other = item
                    self.valueDict.__setitem__(self.refName, value,
                                               self.previous, self.next,
                                               self.alias, False)

                elif isinstance(value._item, Stub):
                    value._item = item
                    self.valueDict.__setitem__(self.refName, value,
                                               self.previous, self.next,
                                               self.alias, False)
                else:
                    return value

            else:
                if self.ref is not None:
                    self.ref.attach(item, self.attrName,
                                    other, self.otherName, self.otherCard)
                else:
                    value = ItemRef(item, self.attrName,
                                    other, self.otherName, self.otherCard)
                    self.valueDict.__setitem__(self.refName, value,
                                               self.previous, self.next,
                                               self.alias, False)

        else:
            raise ValueError, value

        return None


class RefDict(LinkedMap):
    """
    This class implements a collection of bi-directional item references, a
    ref collection. A ref collection is a double-linked list mapping UUIDs
    to item references with predictable order. In addition to the UUID-based
    keys used by the implementation, an optional second set of keys, called
    aliases, can be used to name and access the references contained by a
    ref collection. A ref collection can be iterated over its referenced
    items.
    """
    
    class link(LinkedMap.link):

        def __init__(self, value):

            super(RefDict.link, self).__init__(value)
            self._alias = None

    def __init__(self, item, name, otherName, readOnly=False):
        """
        The constructor for this class. A RefDict should not be instantiated
        directly but created through the item and attribute it is going to
        be used with instead, as for example with: C{item.name = []}.
        """
        
        self._name = name
        self._otherName = otherName
        self._setItem(item)
        self._count = 0
        self._aliases = None
        self._readOnly = readOnly
        self._indexes = None
        
        super(RefDict, self).__init__()

    def _copy(self, references, item, copyItem, name, policy, copies):

        refDict = copyItem._refDict(name)
        references[name] = refDict
        
        if policy == 'copy':
            for key in self.iterkeys():
                link = self._get(key)
                other = link._value.other(item)
                refDict.append(other, link._alias)

        elif policy == 'cascade':
            for key in self.iterkeys():
                link = self._get(key)
                other = link._value.other(item)
                copyOther = copies.get(other.itsUUID, None)

                if copyOther is None:
                    if item.itsParent is copyItem.itsParent:
                        otherParent = other.itsParent
                    else:
                        otherParent = copyItem.itsParent
                    copyOther = other.copy(None, otherParent, copies)

                if not copyOther in refDict:
                    refDict.append(copyOther, link._alias)

        return refDict

    def _makeLink(self, value):

        return RefDict.link(value)

    def _setItem(self, item):

        self._item = item

    def _getItem(self):

        return self._item

    def _getRepository(self):

        return self._item.itsView

    def _isTransient(self):

        return False

    def __len__(self):

        return self._count

    def __repr__(self):

        return '<%s: %s.%s.%s>' %(type(self).__name__,
                                  self._getItem().itsPath,
                                  self._name, self._otherName)

    def __contains__(self, obj):
        """
        The C{in} operator works both with C{Item} values or C{UUID} keys.

        To verify if there is a value for an alias, use the
        L{resolveAlias} method instead.
        """

        load = not self._item.isNew()
        if isinstance(obj, ItemPackage.Item.Item):
            return self.has_key(obj._uuid, load)

        return self.has_key(obj, load)

    def addIndex(self, name, indexType, **kwds):

        index = self._createIndex(indexType, **kwds)

        if self._indexes is None:
            self._indexes = { name: index }
        else:
            self._indexes[name] = index

        if not self._getRepository().isLoading():
            self.fillIndex(index)
            self._item.setDirty(attribute=self._name, dirty=self._item.RDIRTY)

    def _createIndex(self, indexType, *args, **kwds):

        if indexType == 'numeric':
            return NumericIndex(*args, **kwds)

        raise NotImplementedError, "indexType: %s" %(indexType)

    def removeIndex(self, name):

        del self._indexes[name]
        self._item.setDirty(attribute=self._name, dirty=self._item.RDIRTY)

    def fillIndex(self, index):

        for key in self.iterkeys():
            link = self._get(key)
            index.insertKey(key, link._previousKey)

    def _restoreIndexes(self):

        for index in self._indexes.itervalues():
            if index.isPersistent():
                index._restore(self._item._version)
            else:
                self.fillIndex(index)

    def extend(self, valueList):
        """
        As with regular python lists, this method appends all items in the
        list to this ref collection.
        """
        
        for value in valueList:
            self.append(value)

    def update(self, dictionary, setAliases=False):
        """
        As with regular python dictionary, this method appends all items in
        the dictionary to this ref collection.

        @param setAliases: if C{True}, the keys in the dictionary are used
        as aliases for the references added to this ref collection. The keys
        should be strings.
        @type setAliases: boolean
        """

        if setAliases:
            for alias, value in dictionary.iteritems():
                self.append(value, alias)
        else:
            for value in dictionary.itervalues():
                self.append(value)

    def append(self, item, alias=None):
        """
        Append an item to this ref collection.

        @param alias: if this optional argument is specified it becomes an
        alias with which the item can be looked up using the L{getByAlias}
        or L{resolveAlias} methods.
        @type alias: a string
        """

        self.__setitem__(item._uuid, item, alias=alias)

    def clear(self):
        """
        Remove all references from this ref collection.
        """
        
        key = self.firstKey()
        while key is not None:
            nextKey = self.nextKey(key)
            del self[key]
            key = nextKey

    def dir(self):
        """
        Debugging: print all items referenced in this ref collection.
        """

        for item in self:
            print item

    def __getitem__(self, key):

        return self._getRef(key).other(self._getItem())

    def __setitem__(self, key, value,
                    previousKey=None, nextKey=None, alias=None,
                    load=True):

        loading = self._getRepository().isLoading()
        if not loading:
            self._changeRef(key)

        if loading and previousKey is None and nextKey is None:
            ref = self._loadRef(key)
            if ref is not None:
                previousKey, nextKey, alias = ref
        
        old = super(RefDict, self).get(key, None, load)
        if old is not None:
            item = self._getItem()
            if type(value) is ItemRef:
                old.detach(item, self._name,
                           old.other(item), self._otherName)
            else:
                if value is not old.other(item):
                    self._getRepository().logger.warning('Warning: reattaching %s for %s on %s',
                                                         value,
                                                         old.other(item),
                                                         self._name)
                    old.reattach(item, self._name,
                                 old.other(item), value, self._otherName)
                return old

        if type(value) is not ItemRef:
            value = ItemRef(self._getItem(), self._name,
                            value, self._otherName)

        link = super(RefDict, self).__setitem__(key, value,
                                                previousKey, nextKey)
        if not loading:
            self._count += 1
            if self._indexes:
                for index in self._indexes.itervalues():
                    index.insertKey(key, previousKey)

        if alias:
            link._alias = alias
            if self._aliases is None:
                self._aliases = { alias: key }
            else:
                self._aliases[alias] = key

        return value

    def placeItem(self, item, after, indexName=None):
        """
        Place an item in this collection after another one.

        Both items must already belong to the collection. To place an item
        first, pass C{None} for C{after}.

        @param item: the item to place, must belong to the collection.
        @type item: an C{Item} instance
        @param after: the item to place C{item} after or C{None} if C{item} is
        to be first in this ref collection.
        @type after: an C{Item} instance
        @param indexName: the name of an index to use instead of the
        collection's default intrinsic order
        @type indexName: a string
        """
        
        key = item._uuid
        if after is not None:
            afterKey = after._uuid
        else:
            afterKey = None

        if indexName is None:
            super(RefDict, self).place(key, afterKey)
        else:
            self._indexes[indexName].moveKey(key, afterKey)
            self._item.setDirty(attribute=self._name, dirty=self._item.RDIRTY)

    def removeItem(self, item):
        """
        Remove a referenced item from this reference collection.

        @param item: the item whose reference to remove.
        @type item: an C{Item} instance
        """
        
        del self[item._uuid]
            
    def __delitem__(self, key):

        self._removeRef(key, True)

    def _changeRef(self, key, alias=None):

        if self._readOnly:
            raise AttributeError, 'Value for %s on %s is read-only' %(self._name, self._item.itsPath)

        self._item.setDirty(attribute=self._name, dirty=self._item.RDIRTY)

    def _removeRef(self, key, _detach=False):

        if self._readOnly:
            raise AttributeError, 'Value for %s on %s is read-only' %(self._name, self._item.itsPath)

        value = self._getRef(key)

        if _detach:
            value.detach(self._item, self._name,
                         value.other(self._item), self._otherName)

        link = super(RefDict, self).__delitem__(key)
        if link._alias is not None:
            del self._aliases[link._alias]
            
        self._count -= 1
        if self._indexes:
            for index in self._indexes.itervalues():
                index.removeKey(key)

        return link

    def _load(self, key):

        repository = self._item.itsView
        loading = None
        
        try:
            loading = repository._setLoading()
            ref = self._loadRef(key)
            if ref is not None:
                args = RefArgs(self._name, key, key,
                               self._otherName, None, self,
                               ref[0], ref[1], ref[2])
                value = args.attach(self._item, repository)
                if value is not None:
                    self.__setitem__(args.refName, value, args.previous,
                                     args.next, args.alias, False)
                    
                return True
        finally:
            if loading is not None:
                repository._setLoading(loading)

        return False

    def _unload(self, item):

        for link in self._itervalues():
            link._value._unload(item)

    def _loadRef(self, key):

        return None

    def linkChanged(self, link, key):

        if key is not None:
            self._changeRef(key)

    def _getRef(self, key, load=True):

        load = load and not self._item.isNew()
        return super(RefDict, self).__getitem__(key, load)

    def get(self, key, default=None, load=True):
        """
        Get the item referenced at C{key}.

        To get an item through its alias, use L{getByAlias} instead.

        @param key: the UUID of the item referenced.
        @type key: L{UUID<repository.util.UUID.UUID>}
        @param default: the default value to return if there is no reference
        for C{key} in this ref collection, C{None} by default.
        @type default: anything
        @param load: if the reference exists but hasn't been loaded yet,
        this method will return C{default} if this parameter is C{False}.
        @type load: boolean
        @return: an C{Item} instance or C{default}
        """

        load = load and not self._item.isNew()
        value = super(RefDict, self).get(key, default, load)
        if value is not default:
            return value.other(self._item)

        return default

    def getByAlias(self, alias, default=None, load=True):
        """
        Get the item referenced through its alias.
        
        @param alias: the alias of the item referenced.
        @type key: a string
        @param default: the default value to return if there is no reference
        for C{key} in this ref collection, C{None} by default.
        @type default: anything
        @param load: if the reference exists but hasn't been loaded yet,
        this method will return C{default} if this parameter is C{False}.
        @type load: boolean
        @return: an C{Item} instance or C{default}
        """
        
        key = None

        if self._aliases is not None:
            key = self._aliases.get(alias)
            
        if key is None and load:
            key = self.resolveAlias(alias, load)

        if key is None:
            return default
            
        return self.get(key, default, load)

    def resolveAlias(self, alias, load=True):
        """
        Resolve the alias to its corresponding reference key.

        @param alias: the alias to resolve.
        @type alias: a string
        @param load: if the reference exists but hasn't been loaded yet,
        this method will return C{None} if this parameter is C{False}.
        @type load: boolean
        @return: a L{UUID<repository.util.UUID.UUID>} or C{None} if the
        alias does not exist.
        """
        
        if self._aliases:
            return self._aliases.get(alias)

        return None

    def getByIndex(self, indexName, position):
        """
        Get the item through its position in an index.

        C{position} is 0-based and may be negative to begin search from end
        going backwards with C{-1} being the index of the last element.

        C{IndexError} is raised if C{position} is out of range.

        @param indexName: the name of the index to search
        @type indexName: a string
        @param position: the position of the item in the index
        @type position: integer
        @return: an C{Item} instance
        """

        return self[self._indexes[indexName].getKey(position)]

    def resolveIndex(self, indexName, position):

        return self._indexes[indexName].getKey(position)

    def _refCount(self):

        return len(self)

    def _xmlValue(self, name, item, generator, withSchema, version, flags,
                  mode):

        def addAttr(attrs, attr, value):

            if value is not None:
                if isinstance(value, UUID):
                    attrs[attr + 'Type'] = 'uuid'
                    attrs[attr] = value.str64()
                elif isinstance(attr, str) or isinstance(attr, unicode):
                    attrs[attr] = value.encode('utf-8')
                else:
                    raise NotImplementedError, "%s, type: %s" %(value,
                                                                type(value))

        attrs = { 'name': name }
        
        if withSchema:
            attrs['cardinality'] = 'list'
            attrs['otherName'] = item._kind.getOtherName(name)

        addAttr(attrs, 'first', self._firstKey)
        addAttr(attrs, 'last', self._lastKey)
        attrs['count'] = str(self._count)

        if flags:
            attrs['flags'] = str(flags)

        generator.startElement('ref', attrs)
        self._xmlValues(generator, version, mode)
        generator.endElement('ref')

    def _xmlValues(self, generator, version, mode):

        for key in self.iterkeys():
            link = self._get(key)
            link._value._xmlValue(key, self._item,
                                  generator, False, version, 0, mode,
                                  previous=link._previousKey,
                                  next=link._nextKey,
                                  alias=link._alias)
        if self._indexes:
            for name, index in self._indexes.iteritems():
                attrs = { 'name': name }
                index._xmlValues(generator, version, attrs, mode)

    def copy(self):
        """
        This method is not directly supported on this class.

        To copy a ref collection into another one, call L{extend} with this
        collection on the target collection.
        """
        
        raise NotImplementedError, 'RefDict.copy is not supported'

    def first(self, indexName=None):
        """
        Get the first item referenced in this ref collection.

        @param indexName: the name of an index to use instead of the
        collection's default intrinsic order
        @type indexName: a string
        @return: an C{Item} instance or C{None} if empty.
        """

        if indexName is None:
            firstKey = self.firstKey()
        else:
            firstKey = self._indexes[indexName].getFirstKey()
            
        if firstKey is not None:
            return self[firstKey]

        return None

    def last(self, indexName=None):
        """
        Get the last item referenced in this ref collection.

        @param indexName: the name of an index to use instead of the
        collection's default intrinsic order
        @type indexName: a string
        @return: an C{Item} instance or C{None} if empty.
        """

        if indexName is None:
            lastKey = self.lastKey()
        else:
            lastKey = self._indexes[indexName].getLastKey()
            
        if lastKey is not None:
            return self[lastKey]

        return None

    def next(self, previous, indexName=None):
        """
        Get the next referenced item relative to previous.

        @param previous: the previous item relative to the item sought.
        @type previous: a C{Item} instance
        @param indexName: the name of an index to use instead of the
        collection's default intrinsic order
        @type indexName: a string
        @return: an C{Item} instance or C{None} if C{previous} is the last
        referenced item in the collection.
        """

        key = previous._uuid

        if indexName is None:
            nextKey = self.nextKey(key)
        else:
            nextKey = self._indexes[indexName].getNextKey(key)

        if nextKey is not None:
            return self[nextKey]

        return None

    def previous(self, next, indexName=None):
        """
        Get the previous referenced item relative to next.

        @param next: the next item relative to the item sought.
        @type next: a C{Item} instance
        @param indexName: the name of an index to use instead of the
        collection's default intrinsic order
        @type indexName: a string
        @return: an C{Item} instance or C{None} if next is the first
        referenced item in the collection.
        """

        key = next._uuid

        if indexName is None:
            previousKey = self.previousKey(key)
        else:
            previousKey = self._indexes[indexName].getPreviousKey(key)

        if previousKey is not None:
            return self[previousKey]

        return None

    def check(self, item, name):
        """
        Debugging: verify this ref collection for consistency.

        Consistency errors are logged.

        @return: C{True} if no errors were found, {False} otherwise.
        """

        l = len(self)
        logger = self._getRepository().logger
        
        key = self.firstKey()
        while key:
            try:
                other = self[key]
            except DanglingRefError, e:
                logger.error('DanglingRefError on %s.%s: %s',
                             self._item.itsPath, self._name, e)
                return False
            except KeyError, e:
                logger.error('KeyError on %s.%s: %s',
                             self._item.itsPath, self._name, e)
                return False
            else:
                if other.isStale():
                    logger.error('Found stale item %s at %s of kind %s',
                                 other, other.itsPath,
                                 other._kind.itsPath)
                    return False
                else:
                    name = other.getAttributeAspect(self._otherName,
                                                    'otherName', default=None)
                    if name != self._name:
                        logger.error("OtherName for attribute %s.%s, %s, does not match otherName for attribute %s.%s, %s",
                                     other._kind.itsPath,
                                     self._otherName, name,
                                     self._item._kind.itsPath,
                                     self._name, self._otherName)
                        return False
                        
            l -= 1
            key = self.nextKey(key)
            
        if l != 0:
            logger.error("Iterator on %s.%s doesn't match length (%d left for %d total)",
                         self._item.itsPath, self._name, l, len(self))
            return False

        return True


class TransientRefDict(RefDict):
    """
    A ref collection class for transient attributes.
    """

    def linkChanged(self, link, key):
        pass
    
    def _changeRef(self, key, alias=None):
        pass

    def check(self, item, name):
        return True

    def _load(self, key):
        return False
    
    def _isTransient(self):
        return True


class DanglingRefError(ValueError):
    pass
