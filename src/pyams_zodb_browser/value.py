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

"""PyAMS_*zodb_browser.value module

"""

import collections
import itertools
import logging
import re
from html import escape

from ZODB.utils import oid_repr, u64
from persistent import Persistent
from persistent.dict import PersistentDict
from persistent.list import PersistentList
from persistent.mapping import PersistentMapping
from zope.interface import Interface
from zope.interface.declarations import ProvidesClass

from pyams_utils.adapter import adapter_config
from pyams_zodb_browser.interfaces import IObjectHistory, IValueRenderer


__docformat__ = 'restructuredtext'


log = logging.getLogger(__name__)


MAX_CACHE_SIZE = 1000
TRUNCATIONS = {}
TRUNCATIONS_IN_ORDER = collections.deque()
next_id = itertools.count(1).__next__  # pylint: disable=invalid-name


def reset_truncations():  # for tests only!
    """Reset truncations"""
    global next_id  # pylint: disable=global-statement,invalid-name
    next_id = itertools.count(1).__next__
    TRUNCATIONS.clear()
    TRUNCATIONS_IN_ORDER.clear()


def prune_truncations():
    """Prune truncations"""
    while len(TRUNCATIONS_IN_ORDER) > MAX_CACHE_SIZE:
        del TRUNCATIONS[TRUNCATIONS_IN_ORDER.popleft()]


def truncate(text):
    """Truncate text"""
    id = 'tr%d' % next_id()  # pylint: disable=redefined-builtin,invalid-name
    TRUNCATIONS[id] = text
    TRUNCATIONS_IN_ORDER.append(id)
    return id


@adapter_config(required=Interface, provides=IValueRenderer)
class GenericValue:
    """Default value renderer.

    Uses the object's __repr__, truncating if too long.
    """

    def __init__(self, context):
        self.context = context

    def _repr(self):
        # hook for subclasses
        if getattr(self.context.__class__, '__repr__', None) is object.__repr__:
            # Special-case objects with the default __repr__ (LP#1087138)
            if isinstance(self.context, Persistent):
                return '<%s.%s with oid %s>' % (
                    self.context.__class__.__module__,
                    self.context.__class__.__name__,
                    oid_repr(self.context._p_oid))  # pylint: disable=protected-access
        try:
            return repr(self.context)
        except Exception:  # pylint: disable=broad-except
            try:
                return '<unrepresentable %s>' % self.context.__class__.__name__
            except Exception:  # pylint: disable=broad-except
                return '<unrepresentable>'

    def render(self, tid=None, can_link=True, limit=200):  # pylint: disable=unused-argument
        """Value renderer"""
        text = self._repr()
        if len(text) > limit:
            id = truncate(text[limit:])  # pylint: disable=redefined-builtin,invalid-name
            text = '%s<span id="%s" class="truncated">...</span>' % (
                escape(text[:limit]), id)
        else:
            text = escape(text)
        if not isinstance(self.context, str):
            try:
                n = len(self.context)  # pylint: disable=invalid-name
            except Exception:  # pylint: disable=broad-except
                pass
            else:
                if n == 1:  # this is a crime against i18n, but oh well
                    text += ' (%d item)' % n
                else:
                    text += ' (%d items)' % n
        return text


def join_with_commas(html, open, close):  # pylint: disable=redefined-builtin
    """Helper to join multiple html snippets into a struct."""
    prefix = open + '<span class="struct">'
    suffix = '</span>'
    for n, item in enumerate(html):  # pylint: disable=invalid-name
        if n == len(html) - 1:
            trailer = close
        else:
            trailer = ','
        if item.endswith(suffix):
            item = item[:-len(suffix)] + trailer + suffix
        else:
            item += trailer
        html[n] = item
    return prefix + '<br />'.join(html) + suffix


@adapter_config(required=str, provides=IValueRenderer)
class StringValue(GenericValue):
    """String renderer."""

    def __init__(self, context):  # pylint: disable=super-init-not-called
        self.context = context

    def render(self, tid=None, can_link=True, limit=200, threshold=4):  # pylint: disable=arguments-differ
        if self.context.count('\n') <= threshold:
            return GenericValue.render(self, tid, can_link=can_link,
                                       limit=limit)
        if isinstance(self.context, str):
            prefix = 'u'
            context = self.context
        else:
            prefix = ''
            context = self.context.decode('latin-1').encode('ascii', 'backslashreplace')
        lines = [re.sub(r'^[ \t]+',
                        lambda m: '&nbsp;' * len(m.group(0).expandtabs()),
                        escape(line))
                 for line in context.splitlines()]
        nl = '<br />'  # pylint: disable=invalid-name
        if sum(map(len, lines)) > limit:
            head = nl.join(lines[:5])
            tail = nl.join(lines[5:])
            id = truncate(tail)  # pylint: disable=redefined-builtin,invalid-name
            return (prefix + "'<span class=\"struct\">" + head + nl
                    + '<span id="%s" class="truncated">...</span>' % id
                    + "'</span>")
        return (prefix + "'<span class=\"struct\">" + nl.join(lines)
                + "'</span>")


@adapter_config(required=tuple, provides=IValueRenderer)
class TupleValue:
    """Tuple renderer."""

    def __init__(self, context):
        self.context = context

    def render(self, tid=None, can_link=True, threshold=100):
        """Value renderer"""
        html = []
        for item in self.context:
            html.append(IValueRenderer(item).render(tid, can_link))
        if len(html) == 1:
            html.append('')  # (item) -> (item, )
        result = '(%s)' % ', '.join(html)
        if len(result) > threshold or '<span class="struct">' in result:
            if len(html) == 2 and html[1] == '':
                return join_with_commas(html[:1], '(', ', )')
            return join_with_commas(html, '(', ')')
        return result


@adapter_config(required=list, provides=IValueRenderer)
class ListValue:
    """List renderer."""

    def __init__(self, context):
        self.context = context

    def render(self, tid=None, can_link=True, threshold=100):
        """Value renderer"""
        html = []
        for item in self.context:
            html.append(IValueRenderer(item).render(tid, can_link))
        result = '[%s]' % ', '.join(html)
        if len(result) > threshold or '<span class="struct">' in result:
            return join_with_commas(html, '[', ']')
        return result


@adapter_config(required=dict, provides=IValueRenderer)
class DictValue:
    """Dict renderer."""

    def __init__(self, context):
        self.context = context

    def render(self, tid=None, can_link=True, threshold=100):
        """Value renderer"""
        html = []
        for key, value in sorted(self.context.items()):
            html.append(IValueRenderer(key).render(tid, can_link) + ': ' +
                        IValueRenderer(value).render(tid, can_link))
        if (sum(map(len, html)) < threshold and
                '<span class="struct">' not in ''.join(html)):
            return '{%s}' % ', '.join(html)
        return join_with_commas(html, '{', '}')


@adapter_config(required=Persistent, provides=IValueRenderer)
class PersistentValue:
    """Persistent object renderer.

    Uses __repr__ and makes it a hyperlink to the actual object.
    """

    view_name = '#zodbbrowser'
    delegate_to = GenericValue

    def __init__(self, context):
        self.context = context

    def render(self, tid=None, can_link=True):
        """Value renderer"""
        obj = self.context
        url = '%s?oid=0x%x' % (self.view_name, u64(self.context._p_oid))  # pylint: disable=protected-access
        if tid is not None:
            url += "&tid=%d" % u64(tid)
            try:
                oldstate = IObjectHistory(self.context).load_state(tid)  # pylint: disable=assignment-from-no-return
                clone = self.context.__class__.__new__(self.context.__class__)
                clone.__setstate__(oldstate)
                clone._p_oid = self.context._p_oid  # pylint: disable=protected-access
                obj = clone
            except Exception:  # pylint: disable=broad-except
                log.debug('Could not load old state for %s 0x%x',
                          self.context.__class__, u64(self.context._p_oid))  # pylint: disable=protected-access
        value = self.delegate_to(obj).render(tid, can_link=False)
        if can_link:
            return '<a class="objlink" href="%s">%s</a>' % (escape(url), value)
        return value


@adapter_config(required=PersistentMapping, provides=IValueRenderer)
class PersistentMappingValue(PersistentValue):
    """Persistent mapping value adapter"""
    delegate_to = DictValue


@adapter_config(context=PersistentList, provides=IValueRenderer)
class PersistentListValue(PersistentValue):
    """Persistent list value adapter"""
    delegate_to = ListValue


if PersistentMapping is PersistentDict:
    # ZODB 3.9 deprecated PersistentDict and made it an alias for
    # PersistentMapping.  I don't know a clean way to conditionally disable the
    # <adapter> directive in ZCML to avoid conflicting configuration actions,
    # therefore I'll register a decoy adapter registered for a decoy class.
    # This adapter will never get used.

    class DecoyPersistentDict(PersistentMapping):
        """Decoy to avoid ZCML errors while supporting both ZODB 3.8 and 3.9."""

    @adapter_config(required=DecoyPersistentDict,
                    provides=IValueRenderer)
    class PersistentDictValue(PersistentValue):
        """Decoy to avoid ZCML errors while supporting both ZODB 3.8 and 3.9."""
        delegate_to = DictValue

else:
    @adapter_config(required=PersistentDict,
                    provides=IValueRenderer)
    class PersistentDictValue(PersistentValue):
        """Persistent dict value adapter"""
        delegate_to = DictValue


@adapter_config(required=ProvidesClass,
                provides=IValueRenderer)
class ProvidesValue(GenericValue):
    """zope.interface.Provides object renderer.

    The __repr__ of zope.interface.Provides is decidedly unhelpful.
    """

    def _repr(self):
        return '<Provides: %s>' % ', '.join(i.__identifier__
                                            for i in self.context._Provides__args[1:])  # pylint: disable=protected-access
