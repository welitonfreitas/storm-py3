#
# Copyright (c) 2006, 2012 Canonical
#
# Written by Gustavo Niemeyer <gustavo@niemeyer.net>
#
# This file is part of Storm Object Relational Mapper.
#
# Storm is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation; either version 2.1 of
# the License, or (at your option) any later version.
#
# Storm is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#


from builtins import object
class Xid(object):
    """
    Represent a transaction identifier compliant with the XA specification.
    """

    def __init__(self, format_id, global_transaction_id, branch_qualifier):
        self.format_id = format_id
        self.global_transaction_id = global_transaction_id
        self.branch_qualifier = branch_qualifier
