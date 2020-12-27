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

"""PyAMS_zodb_browser.diff module

"""

__docformat__ = 'restructuredtext'

from html import escape

from pyams_zodb_browser.interfaces import IValueRenderer


ADDED = 'added'
REMOVED = 'removed'
CHANGED = 'changed to'


def compare_dicts(new, old):
    """Compare two state dictionaries, return dict."""
    diffs = {}
    for key, value in list(new.items()):
        if key not in old:
            diffs[key] = (ADDED, value, None)
        elif old[key] != value:
            diffs[key] = (CHANGED, value, old[key])
    for key, value in list(old.items()):
        if key not in new:
            diffs[key] = (REMOVED, None, value)
    return diffs


def isascii(s):
    """See if the string can be safely converted to unicode."""
    try:
        s.encode('ascii')
    except UnicodeError:
        return False
    else:
        return True


def compare_tuples(new, old):
    """Compare two tuples.

    Return (common_prefix, middle_of_old, middle_of_new, common_suffix)
    """
    first = 0
    for oldval, newval in zip(old, new):
        if oldval != newval:
            break
        first += 1
    last = 0
    for oldval, newval in zip(reversed(old[first:]), reversed(new[first:])):
        if oldval != newval:
            break
        last += 1
    return (old[:first],
            old[first:len(old) - last],
            new[first:len(new) - last],
            old[len(old) - last:])


def compare_tuples_html(new, old, tid=None, indent=''):
    """Compare two tuples, return HTML."""
    html = [indent + '<div class="diff">\n']
    prefix, removed, added, suffix = compare_tuples(new, old)
    if len(prefix) > 0:
        html.append(indent + '  <div class="diffitem %s">\n' % 'same')
        if len(prefix) == 1:
            html.append(indent + '    first item kept the same\n')
        else:
            html.append(indent + '    first %d items kept the same\n' % len(prefix))
        html.append(indent + '  </div>\n')
    for oldval in removed:
        html.append(indent + '  <div class="diffitem %s">\n' % REMOVED)
        html.append(indent + '    %s %s\n' % (
            REMOVED, IValueRenderer(oldval).render(tid)))
        html.append(indent + '  </div>\n')
    for newval in added:
        html.append(indent + '  <div class="diffitem %s">\n' % ADDED)
        html.append(indent + '    %s %s\n' % (
            ADDED, IValueRenderer(newval).render(tid)))
        html.append(indent + '  </div>\n')
    if len(suffix) > 0:
        html.append(indent + '  <div class="diffitem %s">\n' % 'same')
        if len(suffix) == 1:
            html.append(indent + '    last item kept the same\n')
        else:
            html.append(indent + '    last %d items kept the same\n' % len(suffix))
        html.append(indent + '  </div>\n')
    html.append(indent + '</div>\n')
    return ''.join(html)


def compare_dicts_html(new, old, tid=None, indent=''):
    """Compare two state dictionaries, return HTML."""
    html = [indent + '<div class="diff">\n']
    diff = compare_dicts(new, old)
    for key, (action, newvalue, oldvalue) in sorted(list(diff.items()),
                                                    key=lambda k_v: (str(type(k_v[0])), k_v[0])):
        what = action.split()[0]
        html.append(indent + '  <div class="diffitem %s">\n' % escape(what))
        if isinstance(key, str) and isascii(key):
            html.append(indent + '    <strong>%s</strong>: ' % escape(key))
        else:
            html.append(indent + '    <strong>%s</strong>: ' % IValueRenderer(key).render(tid))
        if (action == CHANGED and isinstance(oldvalue, dict) and isinstance(newvalue, dict)):
            html.append('dictionary changed:\n')
            html.append(compare_dicts_html(newvalue, oldvalue, tid, indent=indent + '    '))
        elif (action == CHANGED and isinstance(oldvalue, tuple) and isinstance(newvalue, tuple)):
            html.append('tuple changed:\n')
            html.append(compare_tuples_html(newvalue, oldvalue, tid, indent=indent + '    '))
        else:
            html.append(action)
            html.append(' ')
            if action == REMOVED:
                value = oldvalue
            else:
                value = newvalue
            html.append(IValueRenderer(value).render(tid))
            html.append('\n')
        html.append(indent + '  </div>\n')
    html.append(indent + '</div>\n')
    return ''.join(html)
