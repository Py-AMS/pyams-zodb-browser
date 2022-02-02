#
# Copyright (c) 2015-2020 Thierry Florac <tflorac AT ulthar.net>
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#

"""PyAMS_zodb_browser.btreesupport module

"""

__docformat__ = 'restructuredtext'

from BTrees.OOBTree import OOBTree, OOBucket
from zope.component import getMultiAdapter
from zope.container.btree import BTreeContainer
from zope.container.folder import Folder

from pyams_utils.adapter import adapter_config
from pyams_zodb_browser.history import ZODBObjectHistory
from pyams_zodb_browser.interfaces import IObjectHistory, IStateInterpreter
from pyams_zodb_browser.state import GenericState


@adapter_config(required=OOBTree,
                provides=IObjectHistory)
class OOBTreeHistory(ZODBObjectHistory):
    """OOBTree history adapter"""

    def _load(self):
        # find all objects (tree and buckets) that have ever participated in
        # this OOBTree
        queue = [self._obj]
        seen = set(self._oid)
        history_of = {}
        while queue:
            obj = queue.pop(0)
            history = history_of[obj._p_oid] = ZODBObjectHistory(obj)
            for d in history:
                state = history.load_state(d['tid'])
                if state and len(state) > 1:
                    bucket = state[1]
                    if bucket._p_oid not in seen:
                        queue.append(bucket)
                        seen.add(bucket._p_oid)
        # merge the histories of all objects
        by_tid = {}
        for h in list(history_of.values()):
            for d in h:
                by_tid.setdefault(d['tid'], d)
        self._history = list(by_tid.values())
        self._history.sort(key=lambda d: d['tid'], reverse=True)
        self._index_by_tid()

    def _last_real_change(self, tid=None):
        return ZODBObjectHistory(self._obj).last_change(tid)

    def load_state_pickle(self, tid=None):
        # lastChange would return the tid that modified self._obj or any
        # of its subobjects, thanks to the history merging done by _load.
        # We need the real last change value.
        # XXX: this is used to show the pickled size of an object.  It
        # will be misleading for BTrees if we show just the size for the
        # main BTree object while we're hiding all the individual buckets.
        return self._connection._storage.loadSerial(self._obj._p_oid,
                                                    self._last_real_change(tid))

    def load_state(self, tid=None):
        # lastChange would return the tid that modified self._obj or any
        # of its subobjects, thanks to the history merging done by _load.
        # We need the real last change value.
        return self._connection.oldstate(self._obj, self._last_real_change(tid))

    def rollback(self, tid):
        """Transaction rollback"""
        state = self.load_state(tid)
        if state != self.load_state():
            self._obj.__setstate__(state)
            self._obj._p_changed = True

        while state and len(state) > 1:
            bucket = state[1]
            bucket_history = IObjectHistory(bucket)
            state = bucket_history.load_state(tid)
            if state != bucket_history.load_state():
                bucket.__setstate__(state)
                bucket._p_changed = True


@adapter_config(required=(OOBTree, tuple, None),
                provides=IStateInterpreter)
class OOBTreeState:
    """Non-empty OOBTrees have a complicated tuple structure."""

    def __init__(self, type, state, tid):
        self._items = []
        # A BTree has two kinds of nodes: internal nodes are OOBTree objects,
        # leaf nodes are OOBucket objects.  Internal nodes contain
        # either OOBTrees or OOBuckets (or nothing, if it's an empty node).
        # Buckets contain actual keys and values.  In addition, each internal
        # node has a firstbucket reference that points to the leftmost
        # grandchild, and each bucket has a nextbucket reference.  We
        # can start at firstbucket and follow nextbucket pointers and we'll
        # get all the items in increasing order by key.
        #
        # The pickled state of an OOBTree can be:
        # - `None` for an empty tree
        # - `((first_bucket_state, ), )` for a tree with one bucket
        # - `((child0, key1, child1, ...), firstbucket)` for the general case
        #
        # The pickled state of an OOBucket is
        # - `((key0, value0, key1, value1, ...),)` for the last bucket
        # - `((key0, value0, key1, value1, ...), next_bucket)` for the general case
        #
        # This is documented in comments in BTreeTemplate.c and BucketTemplate.c.
        if not state:
            state = ()
        else:
            assert isinstance(state, tuple)
        if len(state) == 1:
            firstbucket_state = state[0][0]
        elif len(state) == 2:
            bucket = state[1]
            firstbucket_state = IObjectHistory(bucket).load_state(tid)
        else:
            assert len(state) == 0
            firstbucket_state = ((),)

        state = firstbucket_state
        while True:
            assert isinstance(state, tuple)
            assert 1 <= len(state) <= 2
            items = state[0]
            assert isinstance(items, tuple)
            assert len(items) % 2 == 0
            it = iter(items)
            self._items.extend(zip(it, it))

            if len(state) == 1:
                break

            bucket = state[1]
            state = IObjectHistory(bucket).load_state(tid)

    def get_error(self):
        """Error getter"""
        return None

    def get_name(self):
        """Name getter"""
        return None

    def get_parent(self):
        """Parent getter"""
        return None

    def list_attributes(self):
        """Attributes getter"""
        return None

    def list_items(self):
        """Items getter"""
        return self._items

    def as_dict(self):
        """Dict representation"""
        return dict(self._items)


@adapter_config(required=(OOBTree, type(None), None),
                provides=IStateInterpreter)
class EmptyOOBTreeState(OOBTreeState):
    """Empty OOBTrees pickle to None."""


@adapter_config(required=(Folder, dict, None),
                provides=IStateInterpreter)
class FolderState(GenericState):
    """Convenient access to a Folder's items"""

    def list_items(self):
        """Items getter"""
        data = self.state.get('data')
        if not data:
            return []
        # data will be an OOBTree
        loadedstate = IObjectHistory(data).load_state(self.tid)
        return getMultiAdapter((data, loadedstate, self.tid),
                               IStateInterpreter).list_items()


@adapter_config(required=(BTreeContainer, dict, None),
                provides=IStateInterpreter)
class BTreeContainerState(GenericState):
    """Convenient access to a BTreeContainer's items"""

    def list_items(self):
        # This is not a typo; BTreeContainer really uses
        # _SampleContainer__data, for BBB
        data = self.state.get('_SampleContainer__data')
        if not data:
            return []
        # data will be an OOBTree
        loadedstate = IObjectHistory(data).load_state(self.tid)
        return getMultiAdapter((data, loadedstate, self.tid),
                               IStateInterpreter).list_items()


@adapter_config(required=(OOBucket, tuple, None),
                provides=IStateInterpreter)
class OOBucketState(GenericState):
    """A single OOBTree bucket, should you wish to look at the internals

    Here's the state description direct from BTrees/BucketTemplate.c::

     * For a set bucket (self->values is NULL), a one-tuple or two-tuple.  The
     * first element is a tuple of keys, of length self->len.  The second element
     * is the next bucket, present if and only if next is non-NULL:
     *
     *     (
     *          (keys[0], keys[1], ..., keys[len-1]),
     *          <self->next iff non-NULL>
     *     )
     *
     * For a mapping bucket (self->values is not NULL), a one-tuple or two-tuple.
     * The first element is a tuple interleaving keys and values, of length
     * 2 * self->len.  The second element is the next bucket, present iff next is
     * non-NULL:
     *
     *     (
     *          (keys[0], values[0], keys[1], values[1], ...,
     *                               keys[len-1], values[len-1]),
     *          <self->next iff non-NULL>
     *     )

    OOBucket is a mapping bucket; OOSet is a set bucket.
    """

    def get_error(self):
        """Error getter"""
        return None

    def get_name(self):
        """Name getter"""
        return None

    def get_parent(self):
        """Parent getter"""
        return None

    def list_attributes(self):
        """Attributes getter"""
        return [('_next', self.state[1] if len(self.state) > 1 else None)]

    def list_items(self):
        """Items getter"""
        return zip(self.state[0][::2], self.state[0][1::2])

    def as_dict(self):
        """Dict representation"""
        return dict(self.list_attributes(), _items=dict(self.list_items()))
