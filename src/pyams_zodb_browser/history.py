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

"""PyAMS_zodb_browser.history module

"""

__docformat__ = 'restructuredtext'

import inspect

from ZODB.interfaces import IConnection
from ZODB.utils import tid_repr
from persistent import Persistent
from zope.interface import implementer

from pyams_utils.adapter import adapter_config
from pyams_zodb_browser.cache import get_storage_tids
from pyams_zodb_browser.interfaces import IDatabaseHistory, IObjectHistory


@adapter_config(required=Persistent, provides=IObjectHistory)
class ZODBObjectHistory:
    """ZODB object history adapter"""

    def __init__(self, obj):
        self._obj = obj
        self._connection = self._obj._p_jar
        self._storage = self._connection._storage
        self._oid = self._obj._p_oid
        self._history = None
        self._by_tid = {}

    def __len__(self):
        if self._history is None:
            self._load()
        return len(self._history)

    def _load(self):
        """Load history of changes made to a Persistent object.

        Returns a list of dictionaries, from latest revision to the oldest.
        The dicts have various interesting pieces of data, such as:

            tid -- transaction ID (a byte string, usually 8 bytes)
            time -- transaction timestamp (number of seconds since the Unix epoch)
            user_name -- name of the user responsible for the change
            description -- short description (often a URL)

        See the 'history' method of ZODB.interfaces.IStorage.
        """
        size = 999999999999  # "all of it"; ought to be sufficient
        # NB: ClientStorage violates the interface by calling the last
        # argument 'length' instead of 'size'.  To avoid problems we must
        # use positional argument syntax here.
        # NB: FileStorage in ZODB 3.8 has a mandatory second argument 'version'
        # FileStorage in ZODB 3.9 doesn't accept a 'version' argument at all.
        # This check is ugly, but I see no other options if I want to support
        # both ZODB versions :(
        if 'version' in inspect.getargspec(self._storage.history)[0]:
            version = None
            self._history = self._storage.history(self._oid, version, size)
        else:
            self._history = self._storage.history(self._oid, size=size)
        self._index_by_tid()

    def _index_by_tid(self):
        for record in self._history:
            self._by_tid[record['tid']] = record

    def __getitem__(self, item):
        if self._history is None:
            self._load()
        return self._history[item]

    def last_change(self, tid=None):
        """Get last change transaction id"""
        if self._history is None:
            self._load()
        if tid in self._by_tid:
            # optimization
            return tid
        # sadly ZODB has no API for get revision at or before tid, so
        # we have to find the exact tid
        for record in self._history:
            # we assume records are ordered by tid, newest to oldest
            if tid is None or record['tid'] <= tid:
                return record['tid']
        raise KeyError('%r did not exist in or before transaction %r' %
                       (self._obj, tid_repr(tid)))

    def load_state_pickle(self, tid=None):
        """Pickle state loader"""
        return self._connection._storage.loadSerial(self._obj._p_oid,
                                                    self.last_change(tid))

    def load_state(self, tid=None):
        """State loader"""
        return self._connection.oldstate(self._obj, self.last_change(tid))

    def rollback(self, tid):
        """Transaction rollback"""
        state = self.load_state(tid)
        if state != self.load_state():
            self._obj.__setstate__(state)
            self._obj._p_changed = True


@adapter_config(context=IConnection, provides=IDatabaseHistory)
@implementer(IObjectHistory)
class ZODBHistory:

    def __init__(self, connection):
        self._connection = connection
        self._storage = connection._storage
        self._tids = get_storage_tids(self._storage)

    @property
    def tids(self):
        return tuple(self._tids)  # readonlify

    def __len__(self):
        return len(self._tids)

    def __iter__(self):
        return self._storage.iterator()

    def __getitem__(self, index):
        if isinstance(index, slice):
            tids = self._tids[index]
            if not tids:
                return []
            return self._storage.iterator(tids[0], tids[-1])
