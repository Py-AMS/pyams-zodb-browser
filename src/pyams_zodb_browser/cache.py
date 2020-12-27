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

"""PyAMS_zodb_browser.cache module

"""

__docformat__ = 'restructuredtext'

import weakref
import time


MINUTES = 60
HOURS = 60 * MINUTES

STORAGE_TIDS = weakref.WeakKeyDictionary()


def expired(cache_dict, cache_for):
    """Expiration checker"""
    if 'last_update' not in cache_dict:
        return True
    return time.time() > cache_dict['last_update'] + cache_for


def get_storage_tids(storage, cache_for=5 * MINUTES):
    """Storage transactions ids getter"""
    cache_dict = STORAGE_TIDS.setdefault(storage, {})
    if expired(cache_dict, cache_for):
        if cache_dict.get('tids'):
            first = cache_dict['tids'][-1]
            last = cache_dict['tids'][-1]
            try:
                first_record = next(storage.iterator())
            except StopIteration:
                first_record = None
            if first_record and first_record.tid == first:
                # okay, look for new transactions appended at the end
                new = [t.tid for t in storage.iterator(start=last)]
                if new and new[0] == last:
                    del new[0]
                cache_dict['tids'].extend(new)
            else:
                # first record changed, we must've packed the DB
                cache_dict['tids'] = [t.tid for t in storage.iterator()]
        else:
            cache_dict['tids'] = [t.tid for t in storage.iterator()]
        cache_dict['last_update'] = time.time()
    return cache_dict['tids']
