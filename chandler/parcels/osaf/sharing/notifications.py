#   Copyright (c) 2003-2007 Open Source Applications Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

__all__ = [
    'SharingNotification',
    'SharingNewItemNotification',
    'SharingChangeNotification',
    'SharingConflictNotification'
]

from application import schema
from osaf import pim
import logging
from i18n import ChandlerMessageFactory as _


logger = logging.getLogger(__name__)

class SharingNotification(pim.UserNotification):
    pass

class SharingNewItemNotification(SharingNotification):
    pass

class SharingChangeNotification(SharingNotification):
    attribute = schema.One(schema.Text)
    value = schema.One(schema.Text)

class SharingConflictNotification(SharingChangeNotification):
    remote = schema.One(schema.Text)
    local = schema.One(schema.Text)
