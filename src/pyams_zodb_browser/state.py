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

"""PyAMS_zodb_browser.state module

"""

import logging

import zope.interface.declarations
from ZODB.utils import u64
from persistent.dict import PersistentDict
from persistent.list import PersistentList
from persistent.mapping import PersistentMapping
from zope.component import getMultiAdapter
from zope.container.contained import ContainedProxy
from zope.container.ordered import OrderedContainer
from zope.container.sample import SampleContainer
from zope.interface import Interface, implementer
from zope.interface.interface import InterfaceClass
from zope.interface.interfaces import IInterface
from zope.traversing.interfaces import IContainmentRoot

from pyams_utils.adapter import adapter_config
from pyams_zodb_browser.interfaces import IObjectHistory, IStateInterpreter


__docformat__ = 'restructuredtext'


log = logging.getLogger(__name__)


real_Provides = zope.interface.declarations.Provides


def install_provides_hack():
    """Monkey-patch zope.interface.Provides with a more lenient version.

    A common result of missing modules in sys.path is that you cannot
    unpickle objects that have been marked with directlyProvides() to
    implement interfaces that aren't currently available.  Those interfaces
    are replaced by persistent broken placeholders, which aren classes,
    not interfaces, and aren't iterable, causing TypeErrors during unpickling.
    """
    zope.interface.declarations.Provides = Provides


def flatten_interfaces(args):
    """Flatten interfaces"""
    result = []
    for a in args:  # pylint: disable=invalid-name
        if isinstance(a, (list, tuple)):
            result.extend(flatten_interfaces(a))
        elif IInterface.providedBy(a):
            result.append(a)
        else:
            log.warning('  replacing %s with a placeholder', repr(a))
            result.append(InterfaceClass(a.__name__,
                                         __module__='broken ' + a.__module__))
    return result


def Provides(cls, *interfaces):  # pylint: disable=invalid-name
    """ZCA provides wrapper"""
    try:
        return real_Provides(cls, *interfaces)
    except TypeError as e:  # pylint: disable=invalid-name,broad-except
        log.warning('Suppressing TypeError while unpickling Provides: %s', e)
        args = flatten_interfaces(interfaces)
        return real_Provides(cls, *args)


@implementer(IStateInterpreter)
class ZODBObjectState:
    """Object state interpreter"""

    def __init__(self, obj, tid=None, _history=None):
        self.obj = obj
        if _history is None:
            _history = IObjectHistory(self.obj)
        else:
            assert _history._obj is self.obj
        self.history = _history
        self.tid = None
        self.requested_tid = tid
        self.load_error = None
        self.pickled_state = ''
        self._load()

    def _load(self):
        self.tid = self.history.last_change(self.requested_tid)
        try:
            self.pickled_state = self.history.load_state_pickle(self.tid)
            loaded_state = self.history.load_state(self.tid)
        except Exception as e:  # pylint: disable=broad-except,invalid-name
            self.load_error = "%s: %s" % (e.__class__.__name__, e)
            self.state = LoadErrorState(self.load_error, self.requested_tid)
        else:
            self.state = getMultiAdapter((self.obj, loaded_state, self.requested_tid),
                                         IStateInterpreter)

    def get_error(self):
        """Error getter"""
        return self.load_error

    def list_attributes(self):
        """Attributes getter"""
        return self.state.list_attributes()

    def list_items(self):
        """Items getter"""
        return self.state.list_items()

    def get_parent(self):
        """Parent getter"""
        return self.state.get_parent()

    def get_name(self):
        """Name getter"""
        name = self.state.get_name()
        if name is None:
            # __name__ is not in the pickled state, but it may be defined
            # via other means (e.g. class attributes, custom __getattr__ etc.)
            try:
                name = getattr(self.obj, '__name__', None)
            except Exception:
                # Ouch.  Oh well, we can't determine the name.
                pass
        return name

    def as_dict(self):
        """Dict representation"""
        return self.state.as_dict()

    # These are not part of IStateInterpreter

    def get_object_id(self):
        """Object ID getter"""
        return u64(self.obj._p_oid)

    def is_root(self):
        """Root checker"""
        return IContainmentRoot.providedBy(self.obj)

    def get_parent_state(self):
        """Parent state getter"""
        parent = self.get_parent()
        if parent is None:
            return None
        return ZODBObjectState(parent, self.requested_tid)


@implementer(IStateInterpreter)
class LoadErrorState:
    """Placeholder for when an object's state could not be loaded"""

    def __init__(self, error, tid):
        self.error = error
        self.tid = tid

    def get_error(self):
        """Error getter"""
        return self.error

    def get_name(self):
        """Name getter"""
        return None

    def get_parent(self):
        """Parent getter"""
        return None

    def list_attributes(self):
        """Attributes getter"""
        return []

    def list_items(self):
        """Items getter"""
        return None

    def as_dict(self):
        """Dict representation"""
        return {}


@adapter_config(required=(Interface, dict, None), provides=IStateInterpreter)
class GenericState:
    """Most persistent objects represent their state as a dict."""

    def __init__(self, type, state, tid):
        self.state = state
        self.tid = tid

    def get_error(self):
        """Error getter"""
        return None

    def get_name(self):
        """Name getter"""
        return self.state.get('__name__')

    def get_parent(self):
        """Parent getter"""
        return self.state.get('__parent__')

    def list_attributes(self):
        """Attributes getter"""
        return list(self.state.items())

    def list_items(self):
        """Items getter"""
        return None

    def as_dict(self):
        """Dict representation"""
        return self.state


@adapter_config(required=(PersistentMapping, dict, None),
                provides=IStateInterpreter)
class PersistentMappingState(GenericState):
    """Convenient access to a persistent mapping's items."""

    def list_items(self):
        """Items getter"""
        return sorted(self.state.get('data', {}).items())


if PersistentMapping is PersistentDict:
    # ZODB 3.9 deprecated PersistentDict and made it an alias for
    # PersistentMapping.  I don't know a clean way to conditionally disable the
    # <adapter> directive in ZCML to avoid conflicting configuration actions,
    # therefore I'll register a decoy adapter registered for a decoy class.
    # This adapter will never get used.

    class DecoyPersistentDict(PersistentMapping):
        """Decoy to avoid ZCML errors while supporting both ZODB 3.8 and 3.9."""

    @adapter_config(required=(DecoyPersistentDict, dict, None),
                    provides=IStateInterpreter)
    class PersistentDictState(PersistentMappingState):
        """Decoy to avoid ZCML errors while supporting both ZODB 3.8 and 3.9."""

else:

    @adapter_config(required=(PersistentDict, dict, None),
                    provides=IStateInterpreter)
    class PersistentDictState(PersistentMappingState):
        """Convenient access to a persistent dict's items."""


@adapter_config(required=(SampleContainer, dict, None),
                provides=IStateInterpreter)
class SampleContainerState(GenericState):
    """Convenient access to a SampleContainer's items"""

    def list_items(self):
        """Items getter"""
        data = self.state.get('_SampleContainer__data')
        if not data:
            return []
        # data will be something persistent, maybe a PersistentDict, maybe a
        # OOBTree -- SampleContainer itself uses a plain Python dict, but
        # subclasses are supposed to overwrite the _newContainerData() method
        # and use something persistent.
        loaded_state = IObjectHistory(data).load_state(self.tid)
        return getMultiAdapter((data, loaded_state, self.tid),
                               IStateInterpreter).list_items()


@adapter_config(required=(OrderedContainer, dict, None),
                provides=IStateInterpreter)
class OrderedContainerState(GenericState):
    """Convenient access to an OrderedContainer's items"""

    def list_items(self):
        # Now this is tricky: we want to construct a small object graph using
        # old state pickles without ever calling __setstate__ on a real
        # Persistent object, as _that_ would poison ZODB in-memory caches
        # in a nasty way (LP #487243).
        container = OrderedContainer()
        container.__setstate__(self.state)
        if isinstance(container._data, PersistentDict):
            old_data_state = IObjectHistory(container._data).load_state(self.tid)
            container._data = PersistentDict()
            container._data.__setstate__(old_data_state)
        if isinstance(container._order, PersistentList):
            old_order_state = IObjectHistory(container._order).load_state(self.tid)
            container._order = PersistentList()
            container._order.__setstate__(old_order_state)
        return list(container.items())


@adapter_config(required=(ContainedProxy, tuple, None), provides=IStateInterpreter)
class ContainedProxyState(GenericState):
    """Container proxy state interpreter"""

    def __init__(self, proxy, state, tid):
        GenericState.__init__(self, proxy, state, tid)
        self.proxy = proxy

    def get_name(self):
        """Name getter"""
        return self.state[1]

    def get_parent(self):
        """Parent getter"""
        return self.state[0]

    def list_attributes(self):
        """Attributes getter"""
        return [('__name__', self.get_name()),
                ('__parent__', self.get_parent()),
                ('proxied_object', self.proxy.__getnewargs__()[0])]

    def list_items(self):
        """Items getter"""
        return []

    def as_dict(self):
        """Dict representation"""
        return dict(self.list_attributes())


@adapter_config(required=(Interface, Interface, None),
                provides=IStateInterpreter)
class FallbackState:
    """Fallback when we've got no idea how to interpret the state"""

    def __init__(self, type, state, tid):
        self.state = state

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
        return [('pickled state', self.state)]

    def list_items(self):
        """Items getter"""
        return None

    def as_dict(self):
        """Dict representation"""
        return dict(self.list_attributes())
