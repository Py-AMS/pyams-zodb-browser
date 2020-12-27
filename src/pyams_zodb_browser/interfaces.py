#
# Copyright (c) 2015-2019 Thierry Florac <tflorac AT ulthar.net>
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#

"""PyAMS ZODB browser.interfaces module

"""


from zope.interface import Interface


class IObjectHistory(Interface):
    """History of persistent object state.

    Adapt a persistent object to IObjectHistory.
    """

    def __len__(self):
        """Return the number of history records."""

    def __getitem__(self, idx):
        """Return n-th history record.

        Records are ordered by age, from latest (index 0) to oldest.

        Each record is a dictionary with at least the following items:

            tid -- transaction ID (a byte string, usually 8 bytes)
            time -- transaction timestamp (Unix time_t value)
            user_name -- name of the user responsible for the change
            description -- short description (often a URL)

        """

    def last_change(self, tid=None):
        """Return the last transaction at or before tid.

        If tid is not specified, returns the very last transaction that
        modified this object.

        Will raise KeyError if object did not exist before the given
        transaction.
        """

    def load_state(self, tid=None):
        """Load and return the object's historical state at or before tid.

        Returns the unpicked state, not an actual persistent object.
        """

    def load_state_pickle(tid=None):
        """Load and return the object's historical state at or before tid.

        Returns the picked state as a string.
        """

    def rollback(tid):
        """Roll back object state to what it was at or before tid."""


class IDatabaseHistory(Interface):
    """History of the entire database.

    Adapt a connection object to IObjectHistory.
    """

    def __iter__(self, idx):
        """Return an iterator over the history record.

        Records are ordered by age, from oldest (index 0) to newest.

        Each record provides ZODB.interfaces.an IStorageTransactionInformation.
        """


class IValueRenderer(Interface):
    """Renderer of attribute values."""

    def render(self, tid=None, can_link=True):
        """Render object value to HTML.

        Hyperlinks to other persistent objects will be limited to versions
        at or older than the specified transaction id (``tid``).
        """


class IStateInterpreter(Interface):
    """Interprets persistent object state.

    Usually you adapt a tuple (object, state, tid) to IStateInterpreter to
    figure out how a certain object type represents its state for pickling.
    The tid may be None or may be a transaction id, and is supplied in case
    you need to look at states of other objects to make a full sense of this
    one.
    """

    def get_error(self):
        """Return an error message, if there was an error loading this state."""

    def list_attributes(self):
        """Return the attributes of this object as tuples (name, value).

        The order of the attributes returned is irrelevant.

        May return None to indicate that this kind of object cannot
        store attributes.
        """

    def list_items():
        """Return the items of this object as tuples (name, value).

        The order of the attributes returned matters.

        Often these are not stored directly, but extracted from an attribute
        and presented as items for convenience.

        May return None to indicate that this kind of object is not a
        container and cannot store items.
        """

    def get_parent():
        """Return the parent of this object."""

    def get_name():
        """Return the name of this object."""

    def as_dict():
        """Return the state expressed as an attribute dictionary.

        The state should combine the attributes and items somehow, to present
        a complete picture for the purpose of comparing these dictionaries
        while looking for changes.
        """
