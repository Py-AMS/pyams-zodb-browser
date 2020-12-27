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

"""PyAMS_*** module

"""

__docformat__ = 'restructuredtext'

from fanstatic import Library, Resource


library = Library('pyams_zodb_browser', 'resources')


zodbbrowser_css = Resource(library, 'css/zodbbrowser.css',
                           minified='css/zodbbrowser.min.css')

zodbbrowser = Resource(library, 'js/zodbbrowser.js',
                       minified='js/zodbbrowser.min.js',
                       depends=(zodbbrowser_css,))
