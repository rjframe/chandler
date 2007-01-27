#   Copyright (c) 2007 Open Source Applications Foundation
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

__parcel__ = "osaf.views.main"

from osaf.framework.blocks import *
from osaf.views.detail import WatchedItemRootBlock

class SendToolbarItem(WatchedItemRootBlock, ToolbarItem):
    """
    The "Send"/"Update" toolbar item
    """
    def synchronizeWidget(self, useHints=False):
        super(SendToolbarItem, self).synchronizeWidget(useHints)
        self.setState()

    def setState(self):
        # this button to reflect the kind of the selected item
        item = self.item
        if item is not None:
            # modifiedFlags = { "edited":100, "queued":200, "sent":300, "updated":400 }
            if 'edited' in item.modifiedFlags:
                # change the button to "Update"
                pass
            elif 'sent' in  item.modifiedFlags:
                # change the button to "Update"
                pass
            else:
                # leave the bitmap as "Send"
                pass