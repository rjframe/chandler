#   Copyright (c) 2004-2006 Open Source Applications Foundation
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

"""
Classes for the ContentItem Detail View
"""

__parcel__ = "osaf.views.detail"

import sys
import application
import re
from application import schema
from osaf import pim
from osaf.framework.attributeEditors import \
     AttributeEditorMapping, DateTimeAttributeEditor, \
     DateAttributeEditor, TimeAttributeEditor, \
     ChoiceAttributeEditor, StaticStringAttributeEditor
from osaf.framework.blocks import \
     Block, ContainerBlocks, ControlBlocks, MenusAndToolbars, \
     FocusEventHandlers, BranchPoint, debugName
from osaf import sharing
import osaf.pim.mail as Mail
import osaf.pim.items as items
from osaf.pim.tasks import TaskMixin
import osaf.pim.calendar.Calendar as Calendar
import osaf.pim.calendar.Recurrence as Recurrence
from osaf.pim.calendar import TimeZoneInfo
from osaf.pim.contacts import ContactName
from osaf.pim.collections import ListCollection
from osaf.pim import ContentItem
import application.dialogs.Util as Util
import application.dialogs.AccountPreferences as AccountPreferences
import osaf.mail.constants as MailConstants
import osaf.mail.sharing as MailSharing
import osaf.mail.message as MailMessage
from repository.item.Item import Item
import wx
import sets
import logging
from PyICU import ICUError, ICUtzinfo
from datetime import datetime, time, timedelta
from i18n import ChandlerMessageFactory as _
from osaf import messages

import parsedatetime.parsedatetime as parsedatetime 


logger = logging.getLogger(__name__)
    
class DetailRootBlock (FocusEventHandlers, ControlBlocks.ContentItemDetail):
    """
    Root of the Detail View. The prototype instance of this block is copied
    by the BranchPointBlock mechanism every time we build a detail view for a
    new distinct item type.
    """
    def onSetContentsEvent (self, event):
        #logger.debug("%s: onSetContentsEvent: %s, %s", debugName(self), 
                     #event.arguments['item'], event.arguments['collection'])
        Block.Block.finishEdits()
        self.setContentsOnBlock(event.arguments['item'],
                                event.arguments['collection'])

    # This gives us easy access to a proxied version of our contents; where
    # we want the unproxied version, we'll still use self.contents.
    item = property(fget=Block.Block.getProxiedContents, 
                    doc="Return the selected item, or None")

    def getWatchList(self):
        # Tell us if this item's kind changes.
        return [ (self.contents, 'itsKind') ]
    
    def onItemNotification(self, notificationType, data):
        self.markClean() # we'll do whatever needs to be done here.

        if notificationType != 'itemChange':
            return
        
        # Ignore notifications during stamping
        (op, uuid, attributes) = data
        item = self.itsView.findUUID(uuid, False)
        if item is None or item.isMutating():
            #logger.debug("%s: ignoring kind change to %s during stamping.", 
                         #debugName(self), debugName(item))
            return
        
        # It's for us - tell our parent to resync.
        parentBlock = getattr(self, 'parentBlock', None)
        if parentBlock is not None:
            #logger.debug("%s: Resyncing parent block due to kind change on %s", 
                         #debugName(self), debugName(self.contents))
            parentBlock.synchronizeWidget()
        
    def unRender(self):
        # There's a wx bug on Mac (2857) that causes EVT_KILL_FOCUS events to happen
        # after the control's been deleted, which makes it impossible to grab
        # the control's state on the way out. To work around this, the control
        # does nothing in its EVT_KILL_FOCUS handler if it's being deleted,
        # and we'll force the final update here.
        #logger.debug("DetailRoot: unrendering.")
        Block.Block.finishEdits()
        
        # then call our parent which'll do the actual unrender, triggering the
        # no-op EVT_KILL_FOCUS.
        super(DetailRootBlock, self).unRender()
        
    def SelectedItems(self):
        """ 
        Return a list containing the item we're displaying.
        (This gets used for Send)
        """
        return getattr(self, 'contents', None) is not None and [ self.contents ] or []

    def onSendShareItemEvent (self, event):
        """
        Send or Share the current item.
        """
        # finish changes to previous selected item, then do it.
        Block.Block.finishEdits()
        super(DetailRootBlock, self).onSendShareItemEvent(event)
    
    def focus(self):
        """
        Put the focus into the Detail View.
        """
        # Currently, just set the focus to the Title/Headline/Subject
        # Later we may want to support the "preferred" block for
        #  focus within a tree of blocks.
        titleBlock = self.findBlockByName('HeadlineBlock')
        if titleBlock:
            titleBlock.widget.SetFocus()
            titleBlock.widget.SelectAll()

    def synchronizeWidgetDeep(self):
        """ Do synchronizeWidget recursively, depth-first. """
        def syncInside(block):
            # process from the children up
            map(syncInside, block.childrenBlocks)
            block.synchronizeWidget()

        if self.item is not None:
            self.widget.Freeze()
            try:
                syncInside(self)
            finally:
                self.widget.Thaw()
            

class DetailBranchPointDelegate(BranchPoint.BranchPointDelegate):
    """ 
    Delegate for managing trees of blocks that compose the detail view.
    """    
    branchStub = schema.One(Block.Block, doc=
        """
        A stub block to copy as the root of each tree-of-blocks we build.
        Normally, this'll be a DetailRootBlock.
        """)

    schema.addClouds(
        copying = schema.Cloud(byRef=[branchStub])
    )

    def _mapItemToCacheKeyItem(self, item, hints):
        """ 
        Overrides to use the item's kind as our cache key.
        """
        if item is None or item.isDeleting():
            # We use Block's kind itself as the key for displaying "nothing";
            # Mimi wants a particular look when no item is selected; we've got a 
            # particular tree of blocks defined in parcel.xml for this Kind,
            # which will never get used for a real Item.
            return Block.Block.getKind(self.itsView)

        # The normal case: we have an item, so use its Kind
        # as the key.
        return item.itsKind
    
    def _makeBranchForCacheKey(self, keyItem):
        """ 
        Handle a cache miss; build and return the detail tree-of-blocks
        for this keyItem, a Kind.
        """
        # Walk through the keys we have subtrees for, and collect subtrees to use;
        # we decide to use a subtree if _includeSubtree returns True for it.
        # Each subtree we find has children that are the blocks that are to be 
        # collected and sorted (by their 'position' attribute, then their paths
        # to be deterministic in the event of a tie) into the tree we'll use.
        # Blocks without 'position' attributes will naturally be sorted to the end.
        # If we were given a reference to a 'stub' block, we'll copy that and use
        # it as the root of the tree; otherwise, it's assumed that we'll only find
        # one subtree for our key, and use it directly.
        
        # (Yes, I wrote this as a double nested list comprehension with filtering, 
        # but I couldn't decide how to work in a lambda function, so I backed off and
        # opted for clarity.)
        decoratedSubtreeList = [] # each entry will be (position, path, subtreechild)
        itemKinds = set(keyItem.getInheritedSuperKinds())
        itemKinds.add(keyItem)
        for itemKind in itemKinds:
            subtreeAnnotation = BranchPoint.BranchSubtree(itemKind)
            rootBlocks = getattr(subtreeAnnotation, 'rootBlocks', None)
            if rootBlocks is not None:
                for block in rootBlocks:
                    entryTobeSorted = (block.getAttributeValue('position', default=sys.maxint), 
                                       block.itsPath,
                                       self._copyItem(block))
                    decoratedSubtreeList.append(entryTobeSorted) 
                
        if len(decoratedSubtreeList) == 0:
            assert False, "Don't know how to build a branch for this kind!"
            # (We can continue here - we'll end up just caching an empty view.)

        decoratedSubtreeList.sort()
        
        # Copy our stub block and move the new kids on(to) the block
        branch = self._copyItem(self.branchStub)
        branch.childrenBlocks.extend([ block for position, path, block in decoratedSubtreeList ])
        return branch
        
class DetailSynchronizer(Item):
    """
    Mixin class that handles synchronization and notification common to most
    of the blocks in the detail view.
    """
    def onSetContentsEvent (self, event):
        #logger.debug("%s: onSetContentsEvent: %s, %s", debugName(self), 
                     #event.arguments['item'], event.arguments['collection'])
        self.setContentsOnBlock(event.arguments['item'],
                                event.arguments['collection'])

    item = property(fget=Block.Block.getProxiedContents, 
                    doc="Return the selected item, or None")

    def synchronizeWidget(self, useHints=False):
        super(DetailSynchronizer, self).synchronizeWidget(useHints)
        self.show(self.item is not None and self.shouldShow(self.item))
    
    def shouldShow (self, item):
        return True

    def show (self, shouldShow):
        # if the show status has changed, tell our widget, and return True
        try:
            widget = self.widget
        except AttributeError:
            return False
        if shouldShow == widget.IsShown():
            return False
        
        widget.Show(shouldShow)
        self.isShown = shouldShow
        #logger.debug("%s: now %s", debugName(self), 
                     #shouldShow and "visible" or "hidden")
        
        # Re-layout the sizer on the detail view
        block = self
        while block is not None:
            sizer = block.widget.GetSizer()
            if sizer:
                sizer.Layout()
            if block.eventBoundary:
                break
            block = block.parentBlock
        return True

    def onItemNotification(self, notificationType, data):
        self.markClean() # we'll do whatever needs to be done here.
        
        if notificationType != 'itemChange' or not hasattr(self, 'widget'):
            return
        
        # Ignore notifications during stamping or deleting
        (op, uuid, attributes) = data
        changedItem = self.itsView.findUUID(uuid, False)
        if changedItem is None or changedItem.isMutating():
            return
        
        #logger.debug("%s: Resyncing due to change on %s", 
                     #debugName(self), debugName(changedItem))
        self.synchronizeWidget()

class SynchronizedSpacerBlock(DetailSynchronizer, ControlBlocks.StaticText):
    """
    Generic Spacer Block class.
    """

class StaticTextLabel (DetailSynchronizer, ControlBlocks.StaticText):
    def staticTextLabelValue (self, item):
        theLabel = self.title
        return theLabel

    def synchronizeLabel (self, value):
        label = self.widget.GetLabel ()
        relayout = label != value
        if relayout:
            self.widget.SetLabel (value)
        return relayout

    def synchronizeWidget(self, useHints=False):
        super(StaticTextLabel, self).synchronizeWidget(useHints)
        if self.item is not None:
            self.synchronizeLabel(self.staticTextLabelValue(self.item))

def GetRedirectAttribute(item, defaultAttr):
    """
    Gets redirectTo for an attribute name, or just returns the attribute
    name if a there is no redirectTo.
    """
    attributeName = item.getAttributeAspect(defaultAttr, 'redirectTo');
    if attributeName is None:
        attributeName = defaultAttr
    return attributeName


class StaticRedirectAttribute (StaticTextLabel):
    """
    Static text label that displays the attribute value.
    """
    def staticTextLabelValue (self, item):
        try:
            value = item.getAttributeValue(GetRedirectAttribute(item, self.whichAttribute()))
            theLabel = unicode(value)
        except AttributeError:
            theLabel = u""
        return theLabel

class StaticRedirectAttributeLabel (StaticTextLabel):
    """
    Static Text that displays the name of the selected item's Attribute.
    """
    def staticTextLabelValue (self, item):
        redirectAttr = GetRedirectAttribute(item, self.whichAttribute ())
        # lookup better names for display of some attributes
        if item.hasAttributeAspect (redirectAttr, 'displayName'):
            redirectAttr = item.getAttributeAspect (redirectAttr, 'displayName')
        return redirectAttr

class DetailSynchronizedContentItemDetail(DetailSynchronizer, ControlBlocks.ContentItemDetail):
    pass

class DetailSynchronizedAttributeEditorBlock (DetailSynchronizer, ControlBlocks.AEBlock):
    """
    A L{ControlBlocks.AEBlock} that participates in detail view synchronization.
    """
    def OnDataChanged (self):
        # (this is how we find out about drag-and-dropped text changes!)
        self.saveValue()

    def OnFinishChangesEvent (self, event):
        self.saveValue(validate=True)

class DetailStampButton(DetailSynchronizer, ControlBlocks.Button):
    """
    Common base class for the stamping buttons in the Markup Bar.
    """
    def stampMixinClass(self):
        # return the class of this stamp's Mixin Kind (bag of kind-specific attributes)
        raise NotImplementedError, "%s.stampMixinClass()" % (type(self))
        
    def synchronizeWidget(self, useHints=False):
        super(DetailStampButton, self).synchronizeWidget(useHints)

        # toggle this button to reflect the kind of the selected item
        item = self.item
        if item is not None:
            mixinClass = self.stampMixinClass()
            mixinKind = mixinClass.getKind(self.itsView)
            stamped = item.isItemOf(mixinKind)
            if __debug__:
                looksStampedbyClass = isinstance(item, mixinClass)
                assert looksStampedbyClass == stamped, \
                    "Class/Kind mismatch! Item is class %s, kind %s; " \
                    "stamping with class %s, kind %s" % (
                     item.__class__.__name__, 
                     item.itsKind.itsName,
                     mixinClass.__name__, 
                     mixinKind.itsName)
            self.widget.SetState("%s.%s" % (self.icon,
                                 stamped and "Stamped" or "Unstamped"))

    def onButtonPressedEvent (self, event):
        # Rekind the item by adding or removing the associated Mixin Kind
        Block.Block.finishEdits()
        item = self.item
        if item is None or not self._isStampable(item):
            return
            
        mixinKind = self.stampMixinClass().getKind(self.itsView)
        operation = item.itsKind.isKindOf(mixinKind) and 'remove' or 'add'
        
        # Now change the kind and class of this item
        #logger.debug("%s: stamping: %s %s to %s", debugName(self), operation, mixinKind, debugName(item))
        item.StampKind(operation, mixinKind)
        #logger.debug("%s: done stamping: %s %s to %s", debugName(self), operation, mixinKind, debugName(item))

    def onButtonPressedEventUpdateUI(self, event):
        item = self.item
        enable = item is not None and self._isStampable(item) and \
               item.isAttributeModifiable('displayName')
        event.arguments ['Enable'] = enable
        
    def _isStampable(self, item):
        # for now, any ContentItem is stampable. This may change if Mixin rules/policy change

        # @@@MOR Until view merging supports kind changes (or until stamping
        # is accomplished without kind changes), don't allow stamping or
        # unstamping of shared items:
        # @@@BJS Stamping now works from the attribute editors for the stamping
        # columns in the summary too, so I've made the same change there: 
        # see AttributEditors.py's KindAttributeEditor.ReadOnly().
        return (item.isItemOf(items.ContentItem.getKind(self.itsView)) and
            (item.getSharedState() == items.ContentItem.UNSHARED))

class MailMessageButtonBlock(DetailStampButton):
    """ Mail Message Stamping button in the Markup Bar. """
    def stampMixinClass(self): return Mail.MailMessageMixin
    
class CalendarStampBlock(DetailStampButton):
    """ Calendar button in the Markup Bar. """
    def stampMixinClass(self): return Calendar.CalendarEventMixin

class TaskStampBlock(DetailStampButton):
    """ Task button in the Markup Bar. """
    def stampMixinClass(self): return TaskMixin

class PrivateSwitchButtonBlock(DetailSynchronizer, ControlBlocks.Button):
    """ "Never share" button in the Markup Bar. """
    def synchronizeWidget(self, useHints=False):
        # toggle this button to reflect the privateness of the selected item        
        super(PrivateSwitchButtonBlock, self).synchronizeWidget(useHints)
        if self.item is not None:
            self.widget.SetState("%s.%s" % (self.icon,
                                 self.item.private and "Stamped" or "Unstamped"))

    def onButtonPressedEvent(self, event):
        item = self.item
        if item is not None:
            self.postEventByName("FocusTogglePrivate", {'items': [item]})
            # in case the user canceled the dialog, reset markupbar buttons
            self.widget.SetState("%s.%s" % (self.icon,
                                 self.item.private and "Stamped" or "Unstamped"))

    def onButtonPressedEventUpdateUI(self, event):
        item = self.item            
        enable = item is not None and item.isAttributeModifiable('displayName')
        event.arguments ['Enable'] = enable

class ReadOnlyIconBlock(DetailSynchronizer, ControlBlocks.Button):
    """
    "Read Only" icon in the Markup Bar.
    """
    def synchronizeWidget(self, useHints=False):
        # toggle this icon to reflect the read only status of the selected item
        super(ReadOnlyIconBlock, self).synchronizeWidget(useHints)

        checked = self.item is not None and \
               (self.item.getSharedState() == ContentItem.READONLY)
        self.widget.SetState("%s.%s" % (self.icon,
                             checked and "Stamped" or "Unstamped"))

    def onButtonPressedEvent(self, event):
        # We don't actually allow the read only state to be toggled
        pass

    def onButtonPressedEventUpdateUI(self, event):
        enable = self.item is not None and \
               (self.item.getSharedState() == ContentItem.READONLY)
        event.arguments ['Enable'] = enable        

class EditTextAttribute (DetailSynchronizer, ControlBlocks.EditText):
    """
    EditText field connected to some attribute of a ContentItem
    Override LoadAttributeIntoWidget, SaveAttributeFromWidget in subclasses.
    """
    def instantiateWidget (self):
        widget = super (EditTextAttribute, self).instantiateWidget()
        # We need to save off the changed widget's data into the block periodically
        # Hopefully OnLoseFocus is getting called every time we lose focus.
        widget.Bind(wx.EVT_KILL_FOCUS, self.onLoseFocus)
        widget.Bind(wx.EVT_KEY_UP, self.onKeyPressed)
        return widget

    def saveValue(self, validate=False):
        # save the user's edits into item's attibute
        item = self.item
        try:
            widget = self.widget
        except AttributeError:
            widget = None
        if item is not None and widget is not None:
            self.saveAttributeFromWidget(item, widget, validate=validate)
        
    def loadTextValue (self, item):
        # load the edit text from our attribute into the field
        if item is None:
            item = self.item
        if item is not None:
            widget = self.widget
            self.loadAttributeIntoWidget(item, widget)
    
    def onLoseFocus (self, event):
        # called when we get an event; to saves away the data and skips the event
        self.saveValue(validate=True)
        event.Skip()
        
    def onKeyPressed (self, event):
        # called when we get an event; to saves away the data and skips the event
        self.saveValue(validate = event.m_keyCode == wx.WXK_RETURN and self.lineStyleEnum != "MultiLine")
        event.Skip()
        
    def OnDataChanged (self):
        # event that an edit operation has taken place
        self.saveValue()

    def OnFinishChangesEvent (self, event):
        self.saveValue(validate=True)

    def synchronizeWidget(self, useHints=False):
        super(EditTextAttribute, self).synchronizeWidget(useHints)
        if self.item is not None:
            self.loadTextValue(self.item)
            
    def saveAttributeFromWidget (self, item, widget, validate):  
       # subclasses need to override this method
       raise NotImplementedError, "%s.SaveAttributeFromWidget()" % (type(self))

    def loadAttributeIntoWidget (self, item, widget):  
       # subclasses need to override this method
       raise NotImplementedError, "%s.LoadAttributeIntoWidget()" % (type(self))

# @@@ Needs to be rewritten as an attribute editor when attachments become important again.
#class AttachmentAreaBlock(DetailSynchronizedContentItemDetail):
    #"""
    #An area visible only when the item (a mail message) has attachments.
    #"""
    #def shouldShow (self, item):
        #return item is not None and item.hasAttachments()
#class AttachmentTextFieldBlock(EditTextAttribute):
    #"""
    #A read-only list of email attachments, for now.
    #"""
    #def loadAttributeIntoWidget (self, item, widget):
        ## For now, just list the attachments' filenames
        #if item is None or not item.hasAttachments():
            #value = ""
        #else:
            #value = ", ".join([ attachment.filename for attachment in item.getAttachments() if hasattr(attachment, 'filename') ])
        #widget.SetValue(value)
    
    #def saveAttributeFromWidget (self, item, widget, validate):  
        ## It's read-only, but we have to override this method.
        #pass
    
    
# @@@ disabled until we start using this UI again
#class AcceptShareButtonBlock(DetailSynchronizer, ControlBlocks.Button):
    #def shouldShow (self, item):
        #showIt = False
        #if item is not None and not item.isOutbound:
            #try:
                #MailSharing.getSharingHeaderInfo(item)
            #except:       
                #pass
            #else:
                #showIt = True
        ## logger.debug("AcceptShareButton.shouldShow = %s", showIt)
        #return showIt

    #def onAcceptShareEvent(self, event):
        #url, collectionName = MailSharing.getSharingHeaderInfo(self.item)
        #statusBlock = Block.Block.findBlockByName('StatusBar')
        #statusBlock.setStatusMessage( _(u'Subscribing to collection...') )
        #wx.Yield()

        ## If this code is ever revived, it should call sharing.subscribe(),
        ## rather than the following:
        ### share = sharing.Share(itsView=self.itsView)
        ### share.configureInbound(url)
        ### share.get()

        #statusBlock.setStatusMessage( _(u'Subscribed to collection') )
    
        ## @@@ Remove this when the sidebar autodetects new collections
        #collection = share.contents
        #schema.ns("osaf.app", self.itsView).sidebarCollection.add (share.contents)
        ## Need to SelectFirstItem -- DJA

    #def onAcceptShareEventUpdateUI(self, event):
        ## If we're already sharing it, we should disable the button and change the text.
        #enabled = True
        #item = self.item
        #try:
            #url, collectionName = MailSharing.getSharingHeaderInfo(item)
            #existingSharedCollection = sharing.findMatchingShare(self.itsView, url)
        #except:
            #enabled = True
        #else:
            #if existingSharedCollection is not None:
                #self.widget.SetLabel(_("u(Already sharing this collection)"))
                #enabled = False
        #event.arguments['Enable'] = enabled

def getAppearsInNames(item):
    # Only a recurrence master appears 'in' the collection (for 0.6, anyway)
    # so if this item lets us get its master, do so and use that instead.
    getMasterMethod = getattr(item, 'getMaster', None)
    if getMasterMethod is not None:
        item = getMasterMethod()

    if not hasattr(item, 'appearsIn'):
        return () # we won't be visible if this happens.

    # Collect the names and join them into a list
    collectionNames = _(", ").join(sorted(coll.displayName 
                                          for coll in item.appearsIn
                                          if hasattr(coll, 'displayName')))
    return collectionNames
    
class AppearsInAEBlock(DetailSynchronizedAttributeEditorBlock):
    def shouldShow (self, item):
        return len(getAppearsInNames(item)) > 0

class AppearsInAttributeEditor(StaticStringAttributeEditor):
    """
    A read-only list of collections that this item appears in, for now.
    """
    def GetAttributeValue(self, item, attributeName):
        collectionNames = getAppearsInNames(item)
        
        # logger.debug("Returning new appearsin list: %s" % collectionNames)
        # @@@ I18N: FYI: I expect the label & names to be separate fields before too long...
        return _(u"Appears in: %(collectionNames)s") \
               % {'collectionNames': collectionNames }

# Classes to support CalendarEvent details - first, areas that show/hide
# themselves based on readonlyness and attribute values

class CalendarAllDayAreaBlock(DetailSynchronizedContentItemDetail):
    def shouldShow (self, item):
        return item.isAttributeModifiable('allDay')

    def getWatchList(self):
        watchList = super(CalendarAllDayAreaBlock, self).getWatchList()
        watchList.append((self.item, 'allDay'))
        return watchList

class CalendarLocationAreaBlock(DetailSynchronizedContentItemDetail):
    def shouldShow (self, item):
        return item.isAttributeModifiable('location') \
               or hasattr(item, 'location')

    def getWatchList(self):
        watchList = super(CalendarLocationAreaBlock, self).getWatchList()
        watchList.append((self.item, 'location'))
        return watchList
        
class TimeConditionalBlock(Item):
    def shouldShow (self, item):
        return not item.allDay and \
               (item.isAttributeModifiable('startTime') \
                or not item.anyTime)

    def getWatchList(self):
        watchList = super(TimeConditionalBlock, self).getWatchList()
        watchList.extend(((self.item, 'allDay'), 
                          (self.item, 'anyTime')))
        return watchList

class CalendarConditionalLabelBlock(TimeConditionalBlock, StaticTextLabel):
    pass    

class CalendarTimeAEBlock (TimeConditionalBlock,
                           DetailSynchronizedAttributeEditorBlock):
    pass

class ReminderConditionalBlock(Item):
    def shouldShow (self, item):
        return isinstance(item, pim.CalendarEventMixin) and \
               (item.isAttributeModifiable('reminders') \
               or len(item.reminders) > 0)

    def getWatchList(self):
        watchList = super(ReminderConditionalBlock, self).getWatchList()
        watchList.append((self.item, 'reminders'))
        return watchList
    
class ReminderSpacerBlock(ReminderConditionalBlock,
                          SynchronizedSpacerBlock):
    pass

class ReminderAreaBlock(ReminderConditionalBlock,
                        DetailSynchronizedContentItemDetail):
    pass

class ReminderAttributeEditor(ChoiceAttributeEditor):
    def GetControlValue (self, control):
        """
        Get the reminder delta value for the current selection.
        """
        # @@@ i18n For now, assumes that the menu will be a number of minutes, 
        # followed by a space (eg, "1 minute", "15 minutes", etc), or something
        # that doesn't match this (eg, "None") for no-alarm.
        menuChoice = control.GetStringSelection()
        try:
            minuteCount = int(menuChoice.split(u" ")[0])
        except ValueError:
            # "None"
            value = None
        else:
            value = timedelta(minutes=-minuteCount)
        return value

    def SetControlValue (self, control, value):
        """
        Select the choice that matches this delta value.
        """
        # We also take this opportunity to populate the menu
        existingValue = self.GetControlValue(control)
        if existingValue != value or control.GetCount() == 0:            
            # rebuild the list of choices
            choices = self.GetChoices()
            control.Clear()
            control.AppendItems(choices)

            if value is None:
                choiceIndex = 0 # the "None" choice
            else:
                minutes = ((value.days * 1440) + (value.seconds / 60))
                reminderChoice = (minutes == -1) and _(u"1 minute") or (_(u"%(numberOf)i minutes") % {'numberOf': -minutes})
                choiceIndex = control.FindString(reminderChoice)
                # If we can't find the choice, just show "None" - this'll happen if this event's reminder has been "snoozed"
                if choiceIndex == -1:
                    choiceIndex = 0 # the "None" choice
            control.Select(choiceIndex)

    def GetAttributeValue (self, item, attributeName):
        """
        Get the value from the specified attribute of the item.
        """
        return item.userReminderInterval

    def SetAttributeValue (self, item, attributeName, value):
        """Set the value of the attribute given by the value.
        """
        if not self.ReadOnly((item, attributeName)) and \
           value != self.GetAttributeValue(item, attributeName):

            setattr(item, attributeName, value)
            self.AttributeChanged()

class TransparencyConditionalBlock(Item):
    def shouldShow (self, item):
        # don't show for anyTime or @time events (but do show for allDay
        # events, which happen to be anyTime too)
        return not ((item.anyTime and not item.allDay) or not item.duration)

    def getWatchList(self):
        watchList = super(TransparencyConditionalBlock, self).getWatchList()
        watchList.extend(((self.item, 'anyTime'), 
                          (self.item, 'allDay'), 
                          (self.item, 'duration')))
        return watchList

class CalendarTransparencySpacerBlock(TransparencyConditionalBlock, 
                                      SynchronizedSpacerBlock):
    pass

class CalendarTransparencyAreaBlock(TransparencyConditionalBlock, 
                                    DetailSynchronizedContentItemDetail):
    pass

class TimeZoneConditionalBlock(Item):
    def shouldShow (self, item):
        # allDay and anyTime items never show the timezone popup
        if item.allDay or item.anyTime:
            return False

        # Otherwise, it depends on the preference
        tzPrefs = schema.ns('osaf.app', item.itsView).TimezonePrefs
        return tzPrefs.showUI

    def getWatchList(self):
        watchList = super(TimeZoneConditionalBlock, self).getWatchList()
        tzPrefs = schema.ns('osaf.app', self.itsView).TimezonePrefs
        watchList.extend(((self.item, 'allDay'),
                          (self.item, 'anyTime'),
                          (tzPrefs, 'showUI')))
        return watchList

class CalendarTimeZoneSpacerBlock(TimeZoneConditionalBlock, 
                                  SynchronizedSpacerBlock):
    pass

class CalendarTimeZoneAreaBlock(TimeZoneConditionalBlock, 
                                DetailSynchronizedContentItemDetail):
    pass

class CalendarTimeZoneAEBlock(DetailSynchronizedAttributeEditorBlock):
    def getWatchList(self):
        watchList = super(CalendarTimeZoneAEBlock, self).getWatchList()
        timezones = TimeZoneInfo.get(self.itsView)
        watchList.append((timezones, 'wellKnownIDs'))
        return watchList

class RecurrenceConditionalBlock(Item):
    # Centralize the recurrence blocks' visibility decisions. Subclass will
    # declare a visibilityFlags class member composed of these bit values:
    showPopup = 1 # Show the area containing the popup
    showCustom = 2 # Show the area containing the "custom" static string
    showEnds = 4 # Show the area containing the end-date editor

    def recurrenceVisibility(self, item):
        result = 0
        freq = RecurrenceAttributeEditor.mapRecurrenceFrequency(item)
        modifiable = item.isAttributeModifiable('rruleset')
        
        # Show the popup only if it's modifiable, or if it's not
        # modifiable but not the default value.
        if modifiable or (freq != RecurrenceAttributeEditor.onceIndex):
            result |= self.showPopup
                
            if freq == RecurrenceAttributeEditor.customIndex:
                # We'll show the "custom" flag only if we're custom, duh.
                result |= self.showCustom
            elif freq != RecurrenceAttributeEditor.onceIndex:
                # We're not custom and not "once": We'll show "ends" if we're 
                # modifiable, or if we have an "ends" value.
                if modifiable:
                    result |= self.showEnds
                else:
                    try:
                        endDate = item.rruleset.rrules.first().until
                    except AttributeError:
                        pass
                    else:
                        result |= self.showEnds
        return result

    def shouldShow(self, item):
        assert self.visibilityFlags
        return (self.recurrenceVisibility(item) & self.visibilityFlags) != 0
        
    def getWatchList(self):
        watchList = super(RecurrenceConditionalBlock, self).getWatchList()
        watchList.append((self.item, 'rruleset'))
        if self.visibilityFlags & RecurrenceConditionalBlock.showEnds:
            try:
                firstRRule = self.item.rruleset.rrules.first()
            except AttributeError:
                pass
            else:
                watchList.append((firstRRule, 'until'))
        return watchList

class CalendarRecurrencePopupSpacerBlock(RecurrenceConditionalBlock,
                                         SynchronizedSpacerBlock):
    visibilityFlags = RecurrenceConditionalBlock.showPopup
    
class CalendarRecurrencePopupAreaBlock(RecurrenceConditionalBlock,
                                       DetailSynchronizedContentItemDetail):
    visibilityFlags = RecurrenceConditionalBlock.showPopup

class CalendarRecurrenceSpacer2Area(RecurrenceConditionalBlock,
                                    DetailSynchronizer, 
                                    ControlBlocks.StaticText):
    visibilityFlags = RecurrenceConditionalBlock.showPopup | \
                    RecurrenceConditionalBlock.showEnds

class CalendarRecurrenceCustomSpacerBlock(RecurrenceConditionalBlock,
                                          SynchronizedSpacerBlock):
    visibilityFlags = RecurrenceConditionalBlock.showCustom

class CalendarRecurrenceCustomAreaBlock(RecurrenceConditionalBlock,
                                        DetailSynchronizedContentItemDetail):
    visibilityFlags = RecurrenceConditionalBlock.showCustom

class CalendarRecurrenceEndAreaBlock(RecurrenceConditionalBlock,
                                     DetailSynchronizedContentItemDetail):
    visibilityFlags = RecurrenceConditionalBlock.showEnds

# Attribute editor customizations

class CalendarDateAttributeEditor(DateAttributeEditor):    
    def SetAttributeValue(self, item, attributeName, valueString):
        newValueString = valueString.replace('?','').strip()
        if len(newValueString) == 0:
            # Attempting to remove the start date field will set its value to the 
            # "previous value" when the value is committed (removing focus or 
            # "enter"). Attempting to remove the end-date field will set its 
            # value to the "previous value" when the value is committed. In 
            # brief, if the user attempts to delete the value for a start date 
            # or end date, it automatically resets to what value was displayed 
            # before the user tried to delete it.
            self.SetControlValue(self.control, 
                                 self.GetAttributeValue(item, attributeName))
        else:
            oldValue = getattr(item, attributeName, None)
            # Here, the ICUError covers ICU being unable to handle
            # the input value. ValueErrors can occur when I've seen ICU
            # claims to parse bogus  values like "06/05/0506/05/05" 
            #successfully, which causes fromtimestamp() to throw.)
            try:
                dateTimeValue = pim.shortDateFormat.parse(newValueString, 
                                                          referenceDate=oldValue)
            except (ICUError, ValueError):
                # use parsedatetime to calculate the date
                try:
                    cal = parsedatetime.Calendar() 
                    (dateVar, invalidFlag) = cal.parse(newValueString)
                    if dateVar != None and invalidFlag is False:
                        dateTimeValue = datetime(*dateVar[:3])
                    else:
                        self._changeTextQuietly(self.control, "%s ?" % newValueString)
                        return
                except (ValueError):
                    self._changeTextQuietly(self.control, "%s ?" % newValueString)
                    return

            # If this results in a new value, put it back.
            value = datetime.combine(dateTimeValue.date(), oldValue.timetz())
            
            if oldValue != value:
                if attributeName == 'endTime':
                    # Changing the end date or time such that it becomes 
                    # earlier than the existing start date+time will 
                    # change the start date+time to be the same as the 
                    # end date+time (that is, an @time event, or a 
                    # single-day anytime event if the event had already 
                    # been an anytime event).
                    if value < item.startTime:
                        item.startTime = value
                    item.endTime = value
                elif attributeName == 'startTime':
                    item.startTime = value
                else:
                    assert False, "this attribute editor is really just for " \
                                  "start or endtime"

                self.AttributeChanged()
                
            # Refresh the value in place
            self.SetControlValue(self.control, 
                                 self.GetAttributeValue(item, attributeName))

class CalendarTimeAttributeEditor(TimeAttributeEditor):
    zeroHours = pim.durationFormat.parse(_(u"0:00"))
    
    def GetAttributeValue (self, item, attributeName):
        noTime = getattr(item, 'allDay', False) \
               or getattr(item, 'anyTime', False)
        if noTime:
            value = u''
        else:
            value = super(CalendarTimeAttributeEditor, self).GetAttributeValue(item, attributeName)
        return value

    def SetAttributeValue(self, item, attributeName, valueString):
        newValueString = valueString.replace('?','').strip()
        iAmStart = attributeName == 'startTime'
        changed = False
        forceReload = False
        if len(newValueString) == 0:
            if not item.anyTime: # If we're not already anytime
                # Clearing an event's start time (removing the value in it, causing 
                # it to show "HH:MM") will remove both time values (making it an 
                # anytime event).
                if iAmStart:
                    item.anyTime = True
                    changed = True
                else:
                    # Clearing an event's end time will make it an at-time event
                    zeroTime = timedelta()
                    if item.duration != zeroTime:
                        item.duration = zeroTime
                        changed = True
                forceReload = True
        else:
            # We have _something_; parse it.
            oldValue = getattr(item, attributeName)

            # Try to parse it, a couple of different ways; we'll call this
            # generator until it returns something we can parse successfully.
            def generateTimeAttempts(timeString):
                # First, we try as-is. This'll take care of a fully-specified time,
                # including the case of "15:30" in a locale that doesn't use AM/PM.
                yield timeString
                
                # See if we can get hours, minutes, and maybe am/pm out of 
                # what the user typed.
                localeUsesAMPM = len(pim.ampmNames) > 0
                meridian = ""
                format = _(u"%(hour)d:%(minute)02d%(meridian)s")
                if localeUsesAMPM:
                    # This locale uses an am/pm indicator. If one's present,
                    # note it and remove it.
                    (am, pm) = pim.ampmNames
                    (timeString, hasAM) = re.subn(am, '', timeString, 
                                                  re.IGNORECASE)
                    (timeString, hasPM) = re.subn(pm, '', timeString, 
                                                  re.IGNORECASE)
                    if hasAM and hasPM:
                        return # both? bogus.
                    if hasAM or hasPM:
                        meridian = " " + (hasAM and am or pm)
                        timeString = timeString.strip()

                # Now try to get hours & minutes, or just hours, 
                # out of the string. 
                try:
                    hour = int(timeString)
                except ValueError:
                    try:
                        duration = pim.durationFormat.parse(timeString)
                    except (ICUError, ValueError):
                        return # give up.
                    # It looks like a duration:
                    totalSeconds = (duration - CalendarTimeAttributeEditor.zeroHours)
                    hour = int(totalSeconds / 3600)
                    minute = int((totalSeconds % 3600)/ 60)
                else:
                    minute = 0

                if localeUsesAMPM and len(meridian) == 0:
                    # Gotta try to figure out AM vs PM.
                    if hour > 12 and not hasAM:
                        # The hour is unambiguously PM
                        meridian = " " + pm
                        hour -= 12
                    else:
                        # Guess that the user wants the hour closest to the
                        # old time's hour, or noon if we didn't have one.
                        if item.allDay or item.anyTime:
                            oldHour = 12
                        else:
                            oldHour = item.startTime.hour
                        amDiff = abs(oldHour - hour)
                        pmDiff = abs(oldHour - (hour + 12))
                        meridian = " " + (amDiff >= pmDiff and pm or am)
                        
                forceReload = True
                yield format % locals()
                                
            # use parsetime to calculate the time
            gotTime = None
            for valueString in generateTimeAttempts(newValueString):
                try:
                    # use parsedatetime to calculate time
                    cal = parsedatetime.Calendar() 
                    (timeVar, invalidFlag) = cal.parse(valueString)
                    
                    if timeVar != None and invalidFlag is False:
                        newValueString = pim.shortTimeFormat.format(datetime(*timeVar[:5]))
                        gotTime = pim.shortTimeFormat.parse(newValueString, 
                                                         referenceDate=oldValue)
                    else:
                        self._changeTextQuietly(self.control, "%s ?" % newValueString)
                        return
                except (ICUError, ValueError):
                    continue        
                else:
                    break
            
            if gotTime is None:            
                self._changeTextQuietly(self.control, "%s ?" % newValueString)
                return

            # If we got a new value, put it back.
            value = datetime.combine(oldValue.date(), gotTime.timetz())
            # Preserve the time zone!
            value = value.replace(tzinfo=oldValue.tzinfo)
            if item.anyTime or oldValue != value:
                # Something changed.                
                # Implement the rules for changing one of the four values:
                if item.anyTime:
                    # On an anytime event (single or multi-day; both times 
                    # blank & showing the "HH:MM" hint), entering a valid time 
                    # in either time field will set the other date and time 
                    # field to effect a one-hour event on the corresponding date. 
                    item.anyTime = False
                    if iAmStart:
                        item.startTime = value
                    else:
                        item.startTime = value - timedelta(hours=1)
                    item.duration = timedelta(hours=1)
                else:
                    if not iAmStart:
                        # Changing the end date or time such that it becomes 
                        # earlier than the existing start date+time will change 
                        # the start date+time to be the same as the end 
                        # date+time (that is, an @time event, or a single-day 
                        # anytime event if the event had already been an 
                        # anytime event).
                        if value < item.startTime:
                            item.startTime = value
                    setattr (item, attributeName, value)
                    item.anyTime = False
                changed = True
            
        if changed:
            self.AttributeChanged()
            
        if changed or forceReload:
            # Refresh the value in the control
            self.SetControlValue(self.control, 
                             self.GetAttributeValue(item, attributeName))

class RecurrenceAttributeEditor(ChoiceAttributeEditor):
    # These are the values we pass around; they're the same as the menu indices.
    # This is a list of the frequency enumeration names (defined in 
    # Recurrence.py's FrequencyEnum) in the order we present
    # them in the menu... plus "once" at the beginning and "custom" at the end.
    # Note that biweekly is not, in fact, a valid FrequencyEnum frequency, it's a
    # special case.
    # These should not be localized!
    menuFrequencies = [ 'once', 'daily', 'weekly', 'biweekly', 'monthly', 'yearly', 'custom']
    onceIndex = menuFrequencies.index('once')
    customIndex = menuFrequencies.index('custom')
    biweeklyIndex = menuFrequencies.index('biweekly')
    weeklyIndex = menuFrequencies.index('weekly')
    
    @classmethod
    def mapRecurrenceFrequency(theClass, item):
        """
        Map the frequency of this item to one of our menu choices.
        """
        if item.isCustomRule(): # It's custom if it says it is.
            return RecurrenceAttributeEditor.customIndex
        # Otherwise, try to map its frequency to our menu list
        try:
            rrule = item.rruleset.rrules.first() 
            freq = rrule.freq
            # deal with biweekly special case
            if freq == 'weekly' and rrule.interval == 2:
                return RecurrenceAttributeEditor.biweeklyIndex
        except AttributeError:
            # Can't get to the freq attribute, or there aren't any rrules
            # So it's once.
            return RecurrenceAttributeEditor.onceIndex
        else:
            # We got a frequency. Try to map it.
            index = RecurrenceAttributeEditor.menuFrequencies.index(freq)
            if index == -1:
                index = RecurrenceAttributeEditor.customIndex
        return index
    
    def onChoice(self, event):
        control = event.GetEventObject()
        newChoice = self.GetControlValue(control)
        oldChoice = self.GetAttributeValue(self.item, self.attributeName)
        if newChoice != oldChoice:
            # If the old choice was Custom, make sure the user really wants to
            # lose the custom setting
            if oldChoice == RecurrenceAttributeEditor.customIndex:
                caption = _(u"Discard custom recurrence?")
                msg = _(u"The custom recurrence rule on this event will be lost "
                        "if you change it, and you won't be able to restore it."
                        "\n\nAre you sure you want to do this?")
                if not Util.yesNo(wx.GetApp().mainFrame, caption, msg):
                    # No: Reselect 'custom' in the menu
                    self.SetControlValue(control, oldChoice)
                    return

            self.SetAttributeValue(self.item, self.attributeName, 
                                   newChoice)

    def GetAttributeValue(self, item, attributeName):
        index = RecurrenceAttributeEditor.mapRecurrenceFrequency(item)
        return index
    
    def SetAttributeValue(self, item, attributeName, value):
        """
        Set the value of the attribute given by the value.
        """
        assert value != RecurrenceAttributeEditor.customIndex
        # Changing the recurrence period on a non-master item could delete 
        # this very 'item'; if it does, we'll bypass the attribute-changed 
        # notification below...
        if value == RecurrenceAttributeEditor.onceIndex:
            item.removeRecurrence()
        else:
            oldIndex = self.GetAttributeValue(item, attributeName)
            
            # If nothing has changed, return. This avoids building
            # a whole new ruleset, and the teardown of occurrences,
            # as in Bug 5526
            if oldIndex == value:
                return
            
            interval = 1
            if value == RecurrenceAttributeEditor.biweeklyIndex:
                interval = 2
                value = RecurrenceAttributeEditor.weeklyIndex
            duFreq = Recurrence.toDateUtilFrequency(\
                RecurrenceAttributeEditor.menuFrequencies[value])
            rruleset = Recurrence.RecurrenceRuleSet(None, itsView=item.itsView)
            rruleset.setRuleFromDateUtil(Recurrence.dateutil.rrule.rrule(duFreq,
                                         interval=interval))
            until = item.getLastUntil()
            if until is not None:
                rruleset.rrules.first().until = until
            elif hasattr(rruleset.rrules.first(), 'until'):
                del rruleset.rrules.first().until
            rruleset.rrules.first().untilIsDate = True
            item.changeThisAndFuture('rruleset', rruleset)

        self.AttributeChanged()
    
    def GetControlValue (self, control):
        """
        Get the value for the current selection.
        """ 
        choiceIndex = control.GetSelection()
        return choiceIndex

    def SetControlValue (self, control, value):
        """
        Select the choice that matches this index value.
        """
        # We also take this opportunity to populate the menu
        existingValue = self.GetControlValue(control)
        if existingValue != value or control.GetCount() == 0:
            # rebuild the list of choices
            choices = self.GetChoices()
            if self.GetAttributeValue(self.item, self.attributeName) != RecurrenceAttributeEditor.customIndex:
                choices = choices[:-1] # remove "custom"
            control.Clear()
            control.AppendItems(choices)

        control.Select(value)

class RecurrenceCustomAttributeEditor(StaticStringAttributeEditor):
    def GetAttributeValue(self, item, attributeName):
        return item.getCustomDescription()
        
class RecurrenceEndsAttributeEditor(DateAttributeEditor):
    # If we haven't already, remap the configured item & attribute 
    # name to the actual 'until' attribute deep in the recurrence rule.
    # (Because we might be called from within SetAttributeValue,
    # which does the same thing, we just pass through if we're already
    # mapped to 'until')
    def GetAttributeValue(self, item, attributeName):
        if attributeName != 'until':
            attributeName = 'until'
            try:
                item = item.rruleset.rrules.first()
            except AttributeError:
                return u''
        return super(RecurrenceEndsAttributeEditor, self).\
               GetAttributeValue(item, attributeName)
        
    def SetAttributeValue(self, item, attributeName, valueString):
        eventTZ = item.startTime.tzinfo
        
        if attributeName != 'until':
            attributeName = 'until'        
            try:
                item = item.rruleset.rrules.first()
            except AttributeError:
                assert False, "Hey - Setting 'ends' on an event without a recurrence rule?"
        
        # If the user removed the string, remove the attribute.
        newValueString = valueString.replace('?','').strip()
        if len(newValueString) == 0 and hasattr(item, 'until'):
            del item.until
        else:
            try:
                oldValue = getattr(item, attributeName, None)
                dateValue = pim.shortDateFormat.parse(newValueString, 
                                                      referenceDate=oldValue)
            except (ICUError, ValueError):
                self._changeTextQuietly(self.control, "%s ?" % newValueString)
                return

            # set the end timezone to be the same as the event's timezone,
            # unless it's floating.  Allowing a floating recurrence end timezone 
            # has the nonsensical result that the number of occurrences depends
            # on what timezone you view the calendar in if startTime ever 
            # changes to a non-floating timezone.        
            if eventTZ == ICUtzinfo.floating:
                eventTZ == ICUtzinfo.default            

            value = datetime.combine(dateValue.date(), time(0, tzinfo=eventTZ))
            # don't change the value unless the date the user sees has
            # changed
            if oldValue is None or oldValue.date() != value.date():
                # Refresh the value in place
                self.SetControlValue(self.control, 
                                     pim.shortDateFormat.format(value))

                # Change the value in the domain model, asynchronously
                # (because setting recurrence-end could cause this item
                # to be destroyed, which'd cause this widget to be deleted,
                # and we still have references to it in our call stack)
                def changeRecurrenceEnd(self, item, newEndValue):                    
                    item.untilIsDate = True
                    item.until = value
                    self.AttributeChanged()
                wx.CallAfter(changeRecurrenceEnd, self, item, value)

class OutboundOnlyAreaBlock(DetailSynchronizedContentItemDetail):
    """ 
    This block will only be visible on outbound messages
    (like the outbound version of 'from', and 'bcc' which won't ever
    show a value for inbound messages.)
    """
    def shouldShow (self, item):
        return item.isOutbound

    def whichAttribute(self):
        return 'isOutbound'
           
class InboundOnlyAreaBlock(DetailSynchronizedContentItemDetail):
    """
    This block will only be visible on inbound messages
    (like the inbound version of 'from'.)
    """
    def shouldShow (self, item):
        return not item.isOutbound

    def whichAttribute(self):
        return 'isOutbound'

class OutboundEmailAddressAttributeEditor(ChoiceAttributeEditor):
    """
    An attribute editor that presents a list of the configured email
    accounts.

    If no accounts are configured, the only choice will trigger the
    email-account setup dialog.

    This editor's value is the email address string itself (though
    the "configure accounts" choice is treated as the special string '').
    """

    def CreateControl(self, forEditing, readOnly, parentWidget, 
                      id, parentBlock, font):
        control = super(OutboundEmailAddressAttributeEditor, 
                        self).CreateControl(forEditing, readOnly, parentWidget, 
                                            id, parentBlock, font)
        control.Bind(wx.EVT_LEFT_DOWN, self.onLeftClick)
        return control
    
    def onLeftClick(self, event):
        control = event.GetEventObject()
        if control.GetCount() == 1 and self.GetControlValue(control) == u'':
            # "config accounts..." is the only choice
            # Don't wait for the user to make a choice - do it now.
            self.onChoice(event)
        else:
            event.Skip()
        
    def GetChoices(self):
        """
        Get the choices we're presenting.
        """
        choices = []
        for acct in Mail.DownloadAccountBase.getKind(self.item.itsView).iterItems():
            if (acct.isActive and acct.replyToAddress is not None 
                and len(acct.replyToAddress.emailAddress) > 0):
                addr = unicode(acct.replyToAddress) # eg "name <addr@ess>"
                if not addr in choices:
                    choices.append(addr)

        # Also include any SMTP accounts which have their 'fromAddress' set:
        for acct in Mail.SMTPAccount.getKind(self.item.itsView).iterItems():
            if (acct.isActive and acct.fromAddress is not None 
                and len(acct.fromAddress.emailAddress) > 0):
                addr = unicode(acct.fromAddress) # eg "name <addr@ess>"
                if not addr in choices:
                    choices.append(addr)

        choices.append(_(u"Configure email accounts..."))            
        return choices
    
    def GetControlValue (self, control):
        choiceIndex = control.GetSelection()
        if choiceIndex == -1:
            return None
        if choiceIndex == control.GetCount() - 1:
            return u''
        return control.GetString(choiceIndex)

    def SetControlValue (self, control, value):
        """
        Select the choice with the given text.
        """
        # We also take this opportunity to populate the menu
        existingValue = self.GetControlValue(control)
        if existingValue in (None, u'') or existingValue != value:            
            # rebuild the list of choices
            choices = self.GetChoices()
            control.Clear()
            control.AppendItems(choices)
        
            choiceIndex = control.FindString(value)
            if choiceIndex == wx.NOT_FOUND:
                # Weird, we can't find the selected address. Select the
                # "accounts..." choice, which is last.
                choiceIndex = len(choices) - 1
            control.Select(choiceIndex)

    def GetAttributeValue(self, item, attributeName):
        attrValue = getattr(item, attributeName, None)
        if attrValue is not None:
            # Just format one address
            value = unicode(attrValue)
        else:
            value = u''
        return value

    def SetAttributeValue(self, item, attributeName, valueString):
        # Process the one address we've got.
        processedAddresses, validAddresses, invalidCount = \
            Mail.EmailAddress.parseEmailAddresses(item.itsView, valueString)
        if invalidCount == 0:
            # The address is valid. Put it back if it's different
            oldValue = self.GetAttributeValue(item, attributeName)
            if oldValue != processedAddresses:
                value = len(validAddresses) > 0 \
                      and validAddresses[0] or None
                setattr(item, attributeName, value)
                self.AttributeChanged()
                    
    def onChoice(self, event):
        control = event.GetEventObject()
        newChoice = self.GetControlValue(control)
        if len(newChoice) == 0:
            app = wx.GetApp()
            response = application.dialogs.AccountPreferences.\
                     ShowAccountPreferencesDialog(app.mainFrame, 
                                                  account=None, 
                                                  rv=self.item.itsView)
            # rebuild the list in the popup
            self.SetControlValue(control, 
                self.GetAttributeValue(self.item, self.attributeName))
        else:
            #logger.debug("OutboundEmailAddressAttributeEditor.onChoice: "
                         #"new choice is %s", newChoice)
            self.SetAttributeValue(self.item, self.attributeName, \
                                   newChoice)
        
        
class HTMLDetailArea(DetailSynchronizer, ControlBlocks.ItemDetail):
    def synchronizeWidget(self, useHints=False):
        super(HTMLDetailArea, self).synchronizeWidget(useHints)
        if self.item is not None:
            self.selection = self.item

    def getHTMLText(self, item):
        return u"<html><body>" + item + u"</body></html>"


class EmptyPanelBlock(ControlBlocks.ContentItemDetail):
    """
    A bordered panel, which we use when no item is selected in the calendar.
    """
    def instantiateWidget (self):
        # Make a box with a sunken border - wxBoxContainer will take care of
        # getting the background color from our attribute.
        style = '__WXMAC__' in wx.PlatformInfo \
              and wx.BORDER_SIMPLE or wx.BORDER_STATIC
        widget = ContainerBlocks.wxBoxContainer(self.parentBlock.widget, -1,
                                                wx.DefaultPosition, 
                                                wx.DefaultSize, 
                                                style)
        widget.SetBackgroundColour(wx.WHITE)
        return widget

