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

"""PyAMS_zodb_browser.zmi.views module

"""

__docformat__ = 'restructuredtext'

import time
from html import escape

import transaction
from ZODB.POSException import POSKeyError
from ZODB.utils import oid_repr, p64, tid_repr, u64
from persistent import Persistent, TimeStamp
from persistent.timestamp import TimeStamp
from pyramid.httpexceptions import HTTPFound
from pyramid.view import view_config
from zope.exceptions import UserError
from zope.interface import Interface, implementer

from pyams_layer.interfaces import IPyAMSLayer
from pyams_pagelet.pagelet import pagelet_config
from pyams_security.interfaces.base import MANAGE_SYSTEM_PERMISSION
from pyams_site.interfaces import PYAMS_APPLICATION_DEFAULT_NAME, PYAMS_APPLICATION_SETTINGS_KEY
from pyams_skin.interfaces.view import IInnerPage
from pyams_template.template import template_config
from pyams_utils.adapter import ContextRequestAdapter
from pyams_utils.property import cached_property
from pyams_viewlet.viewlet import viewlet_config
from pyams_zmi.interfaces import IAdminLayer
from pyams_zmi.interfaces.viewlet import IControlPanelMenu
from pyams_zmi.zmi.viewlet.menu import NavigationMenuItem
from pyams_zodb_browser.diff import compare_dicts_html
from pyams_zodb_browser.history import ZODBObjectHistory
from pyams_zodb_browser.interfaces import IDatabaseHistory, IValueRenderer
from pyams_zodb_browser.state import ZODBObjectState


from pyams_zodb_browser import _
from pyams_zodb_browser.value import TRUNCATIONS, prune_truncations


def get_object_type(obj):
    """Object type getter"""
    cls = getattr(obj, '__class__', None)
    if type(obj) is not cls:
        return '%s - %s' % (type(obj), cls)
    return str(cls)


def get_object_type_short(obj):
    """Short object type getter"""
    cls = getattr(obj, '__class__', None)
    if type(obj) is not cls:
        return '%s - %s' % (type(obj).__name__, cls.__name__)
    return cls.__name__


def get_object_path(obj, tid):
    """Object path getter"""
    path = []
    seen_root = False
    state = ZODBObjectState(obj, tid)
    while True:
        if state.is_root():
            path.append('/')
            seen_root = True
        else:
            if path:
                path.append('/')
            if not state.get_name() and state.get_parent_state() is None:
                # not using hex() because we don't want L suffixes for
                # 64-bit values
                path.append('0x%x' % state.get_object_id())
                break
            path.append(state.get_name() or '???')
        state = state.get_parent_state()
        if state is None:
            if not seen_root:
                path.append('/')
                path.append('...')
                path.append('/')
            break
    return ''.join(path[::-1])


class ZODBObjectAttribute:
    """Object attributes"""

    def __init__(self, name, value, tid=None):
        self.name = name
        self.value = value
        self.tid = tid

    def rendered_name(self):
        """Attribute name renderer"""
        return IValueRenderer(self.name).render(self.tid)

    def rendered_value(self):
        """Attribute value renderer"""
        return IValueRenderer(self.value).render(self.tid)

    def __repr__(self):
        return '%s(%r, %r, %r)' % (self.__class__.__name__, self.name,
                                   self.value, self.tid)

    def __eq__(self, other):
        if self.__class__ != other.__class__:
            return False
        return (self.name, self.value, self.tid) == (other.name, other.value,
                                                     other.tid)

    def __ne__(self, other):
        return not self.__eq__(other)


@viewlet_config(name='zodbbrowser.menu', context=Interface, layer=IAdminLayer, 
                manager=IControlPanelMenu, weight=999,
                permission=MANAGE_SYSTEM_PERMISSION)
class ZODBBrowserMenu(NavigationMenuItem):
    """ZODB browser menu"""

    label = _("ZODB browser")
    icon_class = 'fas fa-database'
    href = '#zodbbrowser'


class VeryCarefulView(ContextRequestAdapter):
    """Base ZODB view"""

    made_changes = False

    @cached_property
    def jar(self):
        try:
            return self.request.annotations['ZODB.interfaces.IConnection']
        except (KeyError, AttributeError):
            obj = self.find_closest_persistent()
            if obj is None:
                raise Exception("ZODB connection not available for this request")
            return obj._p_jar

    @property
    def readonly(self):
        return self.jar.isReadOnly()

    def find_closest_persistent(self):
        """Find closest persistent object"""
        obj = self.context
        while not isinstance(obj, Persistent):
            try:
                obj = obj.__parent__
            except AttributeError:
                return None
        return obj


@pagelet_config(name='zodbbrowser', context=Interface, layer=IPyAMSLayer, 
                permission=MANAGE_SYSTEM_PERMISSION)
@template_config(template='templates/zodbinfo.pt')
@implementer(IInnerPage)
class ZODBInfoView(VeryCarefulView):
    """ZODB info view"""

    def update(self):
        super(ZODBInfoView, self).update()
        prune_truncations()
        self.obj = self.select_object_to_view()
        # Not using IObjectHistory(self.obj) because LP#1185175
        self.history = ZODBObjectHistory(self.obj)
        self.latest = True
        if self.request.params.get('tid'):
            self.state = ZODBObjectState(self.obj,
                                         p64(int(self.request.params['tid'], 0)),
                                         _history=self.history)
            self.latest = False
        else:
            self.state = ZODBObjectState(self.obj, _history=self.history)

        if 'CANCEL' in self.request.params:
            raise self._redirect_to_self()

        if 'ROLLBACK' in self.request.params:
            rtid = p64(int(self.request.params['rtid'], 0))
            self.requestedState = self._tid_to_timestamp(rtid)
            if self.request.params.get('confirmed') == '1':
                self.history.rollback(rtid)
                transaction.get().note('Rollback to old state %s'
                                       % self.requestedState)
                self.made_changes = True
                transaction.get().commit()
                raise self._redirect_to_self()

    def _redirect_to_self(self):
        return HTTPFound(self.get_url())

    def select_object_to_view(self):
        """View context getter"""
        params = self.request.params
        obj = None
        if 'oid' not in params:
            obj = self.find_closest_persistent()
            # Sanity check: if we're running in standalone mode,
            # self.context is a Folder in the just-created MappingStorage,
            # which we're not interested in.
            if obj is not None and obj._p_jar is not self.jar:
                obj = None
        if obj is None:
            if 'oid' in params:
                try:
                    oid = int(params['oid'], 0)
                except ValueError:
                    raise UserError('OID is not an integer: %r' % params['oid'])
            else:
                oid = self.get_root_oid()
            try:
                obj = self.jar.get(p64(oid))
            except POSKeyError:
                raise UserError('There is no object with OID 0x%x' % oid)
        return obj

    def get_requested_tid(self):
        if 'tid' in self.request.params:
            return self.request.params['tid']
        return None

    def get_requested_tid_nice(self):
        if 'tid' in self.request.params:
            return self._tid_to_timestamp(p64(int(self.request.params['tid'], 0)))
        return None

    def get_object_id(self):
        return self.state.get_object_id()

    def get_object_id_hex(self):
        return '0x%x' % self.state.get_object_id()

    def get_object_type(self):
        return get_object_type(self.obj)

    def get_object_type_short(self):
        return get_object_type_short(self.obj)

    def get_state_tid(self):
        return u64(self.state.tid)

    def get_state_tid_nice(self):
        return self._tid_to_timestamp(self.state.tid)

    def get_pickle_size(self):
        return len(self.state.pickled_state)

    def get_root_oid(self):
        root = self.jar.root()
        try:
            settings = self.request.registry.settings
            root = root[settings.get(PYAMS_APPLICATION_SETTINGS_KEY, 
                                     PYAMS_APPLICATION_DEFAULT_NAME)]
        except KeyError:
            pass
        return u64(root._p_oid)

    def locate(self, path):
        not_found = object()  # marker

        # our current position
        #   partial -- path of the last _persistent_ object
        #   here -- path of the last object traversed
        #   oid -- oid of the last _persistent_ object
        #   obj -- last object traversed
        partial = here = '/'
        oid = self.get_root_oid()
        obj = self.jar.get(p64(oid))

        steps = path.split('/')

        if steps and steps[0]:
            # 0x1234/sub/path -> start traversal at oid 0x1234
            try:
                oid = int(steps[0], 0)
            except ValueError:
                pass
            else:
                partial = here = hex(oid)
                try:
                    obj = self.jar.get(p64(oid))
                except KeyError:
                    oid = self.get_root_oid()
                    return dict(error='Not found: %s' % steps[0],
                                partial_oid=oid,
                                partial_path='/',
                                partial_url=self.get_url(oid))
                steps = steps[1:]

        for step in steps:
            if not step:
                continue
            if not here.endswith('/'):
                here += '/'
            here += step.encode('utf-8')
            try:
                child = obj[step]
            except Exception:
                child = getattr(obj, step, not_found)
                if child is not_found:
                    return dict(error='Not found: %s' % here,
                                partial_oid=oid,
                                partial_path=partial,
                                partial_url=self.get_url(oid))
            obj = child
            if isinstance(obj, Persistent):
                partial = here
                oid = u64(obj._p_oid)
        if not isinstance(obj, Persistent):
            return dict(error='Not persistent: %s' % here,
                        partial_oid=oid,
                        partial_path=partial,
                        partial_url=self.get_url(oid))
        return dict(oid=oid,
                    url=self.get_url(oid))

    def get_url(self, oid=None, tid=None):
        if oid is None:
            oid = self.get_object_id()
        url = "#zodbbrowser?oid=0x%x" % oid
        if tid is None and 'tid' in self.request.params:
            url += "&tid=" + self.request.params['tid']
        elif tid is not None:
            url += "&tid=0x%x" % tid
        return url

    def get_breadcrumbs(self):
        breadcrumbs = []
        state = self.state
        seen_root = False
        while True:
            url = self.get_url(state.get_object_id())
            if state.is_root():
                breadcrumbs.append(('/', url))
                seen_root = True
            else:
                if breadcrumbs:
                    breadcrumbs.append(('/', None))
                if not state.get_name() and state.get_parent_state() is None:
                    # not using hex() because we don't want L suffixes for
                    # 64-bit values
                    breadcrumbs.append(('0x%x' % state.get_object_id(), url))
                    break
                breadcrumbs.append((state.get_name() or '???', url))
            state = state.get_parent_state()
            if state is None:
                if not seen_root:
                    url = self.get_url(self.get_root_oid())
                    breadcrumbs.append(('/', None))
                    breadcrumbs.append(('...', None))
                    breadcrumbs.append(('/', url))
                break
        return breadcrumbs[::-1]

    def get_path(self):
        return ''.join(name for name, url in self.get_breadcrumbs())

    def get_breadcrumbs_html(self):
        html = []
        for name, url in self.get_breadcrumbs():
            if url:
                html.append('<a href="%s">%s</a>' % (escape(url, True),
                                                     escape(name)))
            else:
                html.append(escape(name))
        return ''.join(html)

    def list_attributes(self):
        attrs = self.state.list_attributes()
        if attrs is None:
            return None
        return [ZODBObjectAttribute(name, value, self.state.requested_tid)
                for name, value in sorted(attrs)]

    def list_items(self):
        items = self.state.list_items()
        if items is None:
            return None
        return [ZODBObjectAttribute(name, value, self.state.requested_tid)
                for name, value in items]

    def _load_historical_state(self):
        results = []
        for d in self.history:
            try:
                interp = ZODBObjectState(self.obj, d['tid'],
                                         _history=self.history)
                state = interp.as_dict()
                error = interp.get_error()
            except Exception as e:
                state = {}
                error = '%s: %s' % (e.__class__.__name__, e)
            results.append(dict(state=state, error=error))
        results.append(dict(state={}, error=None))
        return results

    def list_history(self):
        """List transactions that modified a persistent object."""
        state = self._load_historical_state()
        results = []
        for n, d in enumerate(self.history):
            utc_timestamp = str(time.strftime('%Y-%m-%d %H:%M:%S',
                                              time.gmtime(d['time'])))
            local_timestamp = str(time.strftime('%Y-%m-%d %H:%M:%S',
                                                time.localtime(d['time'])))
            try:
                user_location, user_id = d['user_name'].split()
            except ValueError:
                user_location = None
                user_id = d['user_name']
            url = self.get_url(tid=u64(d['tid']))
            current = (d['tid'] == self.state.tid and
                       self.state.requested_tid is not None)
            curState = state[n]['state']
            oldState = state[n + 1]['state']
            diff = compare_dicts_html(curState, oldState, d['tid'])

            results.append(dict(utid=u64(d['tid']),
                                href=url, current=current,
                                error=state[n]['error'],
                                diff=diff, user_id=user_id,
                                user_location=user_location,
                                utc_timestamp=utc_timestamp,
                                local_timestamp=local_timestamp, **d))

        # number in reverse order
        for i in range(len(results)):
            results[i]['index'] = len(results) - i

        return results

    def _tid_to_timestamp(self, tid):
        if isinstance(tid, str) and len(tid) == 8:
            return str(TimeStamp(tid))
        return tid_repr(tid)


@view_config(name='zodbbrowser_path_to_oid', context=Interface, request_type=IPyAMSLayer,
             permission=MANAGE_SYSTEM_PERMISSION, renderer='json', xhr=True)
class PathToOidView(ZODBInfoView):

    def __call__(self):
        path = self.request.params.get('path')
        return self.locate(path)


@view_config(name='zodbbrowser_truncated', context=Interface, request_type=IPyAMSLayer,
             permission=MANAGE_SYSTEM_PERMISSION, renderer='json', xhr=True)
class TruncatedView(ZODBInfoView):

    def __call__(self):
        id = self.request.params.get('id')
        return TRUNCATIONS.get(id)


@pagelet_config(name='zodbbrowser_history', context=Interface, layer=IPyAMSLayer,
                permission=MANAGE_SYSTEM_PERMISSION)
@template_config(template='templates/zodbhistory.pt')
@implementer(IInnerPage)
class ZODBHistoryView(VeryCarefulView):
    """Zodb history view"""

    page_size = 5

    def update(self):
        super(ZODBHistoryView, self).update()
        prune_truncations()
        params = self.request.params
        if 'page_size' in params:
            self.page_size = max(1, int(params['page_size']))
        self.history = IDatabaseHistory(self.jar)
        if 'page' in params:
            self.page = int(params['page'])
        elif 'tid' in params:
            tid = int(params['tid'], 0)
            self.page = self.find_page(p64(tid))
        else:
            self.page = 0
        self.last_page = max(0, len(self.history) - 1) // self.page_size
        if self.page > self.last_page:
            self.page = self.last_page
        self.last_idx = max(0, len(self.history) - self.page * self.page_size)
        self.first_idx = max(0, self.last_idx - self.page_size)

    def get_url(self, tid=None):
        url = "#zodbbrowser_history"
        if tid is None and 'tid' in self.request.params:
            url += "?tid=" + self.request.params['tid']
        elif tid is not None:
            url += "?tid=0x%x" % tid
        return url

    def find_page(self, tid):
        try:
            pos = list(self.history.tids).index(tid)
        except ValueError:
            return 0
        else:
            return (len(self.history) - pos - 1) // self.page_size

    def list_history(self):
        if 'tid' in self.request.params:
            requested_tid = p64(int(self.request.params['tid'], 0))
        else:
            requested_tid = None

        results = []
        for n, d in enumerate(self.history[self.first_idx:self.last_idx]):
            utid = u64(d.tid)
            ts = TimeStamp(d.tid).timeTime()
            utc_timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))
            local_timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
            try:
                user_location, user_id = d.user.split()
            except ValueError:
                user_location = None
                user_id = d.user
            try:
                size = d._tend - d._tpos
            except AttributeError:
                size = None
            ext = d.extension if isinstance(d.extension, dict) else {}
            objects = []
            for record in d:
                obj = self.jar.get(record.oid)
                url = "#zodbbrowser?oid=0x%x&tid=0x%x" % (u64(record.oid),
                                                           utid)
                try:
                    objects.append(dict(
                        oid=u64(record.oid),
                        path=get_object_path(obj, d.tid),
                        oid_repr=oid_repr(record.oid),
                        class_repr=get_object_type(obj),
                        url=url,
                        repr=IValueRenderer(obj).render(d.tid),
                    ))
                except KeyError:  # no history
                    pass
            if len(objects) == 1:
                summary = '1 object record'
            else:
                summary = '%d object records' % len(objects)
            if size is not None:
                summary += ' (%d bytes)' % size
            results.append(dict(
                index=(self.first_idx + n + 1),
                utc_timestamp=utc_timestamp,
                local_timestamp=local_timestamp,
                user_id=user_id,
                user_location=user_location,
                description=d.description,
                utid=utid,
                current=(d.tid == requested_tid),
                href=self.get_url(tid=utid),
                size=size,
                summary=summary,
                hidden=(len(objects) > 5),
                objects=objects,
                **ext
            ))
        if results and not requested_tid and self.page == 0:
            results[-1]['current'] = True
        return results[::-1]
