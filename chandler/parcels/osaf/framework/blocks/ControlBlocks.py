#   Copyright (c) 2003-2008 Open Source Applications Foundation
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


__parcel__ = "osaf.framework.blocks"

import sys
import threading
from application.Application import mixinAClass
from application import schema
from Block import ( 
    Block, RectangularChild, BlockEvent,  BaseWidget, lineStyleEnumType,
    logger, debugName, WithoutSynchronizeWidget, IgnoreSynchronizeWidget
)
from ContainerBlocks import BoxContainer
import DragAndDrop
from chandlerdb.item.ItemError import NoSuchAttributeError
import wx
from wx import html as wxHtml
from wx import gizmos as wxGizmos
from wx import grid as wxGrid
import webbrowser # for opening external links
import PyICU
from util import MultiStateButton
from wx.lib.buttons import GenBitmapTextButton

import application.dialogs.ReminderDialog as ReminderDialog
import Styles
from datetime import datetime, timedelta
from osaf.pim import Reminder, isDead
from i18n import ChandlerMessageFactory as _
from osaf.pim.types import LocalizableString


class textAlignmentEnumType(schema.Enumeration):
    values = "Left", "Center", "Right"

class buttonKindEnumType(schema.Enumeration):
    values = "Text", "Image", "Toggle", "TextImage"

class Button(RectangularChild):
    characterStyle = schema.One(Styles.CharacterStyle)
    title = schema.One(LocalizableString)
    buttonKind = schema.One(buttonKindEnumType)
    icon = schema.One(schema.Text)
    rightClicked = schema.One(BlockEvent)
    event = schema.One(BlockEvent)
    helpString = schema.One(LocalizableString, initialValue = u'')

    def instantiateWidget(self, drawstyle={}):
        id = self.getWidgetID()
        parentWidget = self.parentBlock.widget
        if self.buttonKind == "Text":
            button = wx.Button (parentWidget,
                                id,
                                self.title,
                                wx.DefaultPosition,
                                (self.minimumSize.width, self.minimumSize.height))
        elif self.buttonKind == "Image":
            bitmap = wx.GetApp().GetImage(self.icon)
            button = wx.BitmapButton (parentWidget,
                                      id,
                                      bitmap,
                                      wx.DefaultPosition,
                                      (self.minimumSize.width, self.minimumSize.height))
        elif self.buttonKind == "TextImage":
            bitmap = wx.GetApp().GetImage(self.icon)
            button = GenBitmapTextButton(parentWidget,
                                         id,
                                         bitmap,
                                         self.title,
                                         wx.DefaultPosition,
                                         (self.minimumSize.width, self.minimumSize.height),
                                         style = wx.NO_BORDER,
                                         drawstyle = drawstyle)
            button.SetFont(Styles.getFont(getattr(self, "characterStyle", None)))
        elif self.buttonKind == "Toggle":
            button = wx.ToggleButton (parentWidget, 
                                      id, 
                                      self.title,
                                      wx.DefaultPosition,
                                      (self.minimumSize.width, self.minimumSize.height))
        elif __debug__:
            assert False, "unknown buttonKind"

        parentWidget.Bind(wx.EVT_BUTTON, self.buttonPressed, id=id)
        button.SetName (self.blockName)
        return button

    def buttonPressed(self, event):
        try:
            event = self.event
        except AttributeError:
            pass
        else:
            Block.post(event, {'item':self}, self)

class StampButton(Button):
    def instantiateWidget(self):
        id = self.getWidgetID()
        parentWidget = self.parentBlock.widget

        # for a stamp button, we use "self.icon" as the base name of all bitmaps and look for:
        #
        #   {icon}Normal, {icon}Stamped, {icon}Rollover, {icon}Pressed, {icon}Disabled
        #
        # From these we build two states suffixed "unstamped" and "stamped", which can
        # be used the toggle the appearance of the button.
        #
        assert len(self.icon) > 0
        normal = MultiStateButton.BitmapInfo()
        normal.normal   = "%sNormal" % self.icon
        normal.rollover = "%sRollover" % self.icon
        normal.disabled = "%sDisabled" % self.icon
        normal.selected = "%sPressed" % self.icon
        normal.stateName = "%s.Unstamped" % self.icon
        stamped = MultiStateButton.BitmapInfo()
        stamped.normal   = "%sStamped" % self.icon
        stamped.rollover = "%sStampedRollover" % self.icon
        stamped.disabled = "%sStampedDisabled" % self.icon
        stamped.selected = "%sStampedPressed" % self.icon
        stamped.stateName = "%s.Stamped" % self.icon
        button = wxChandlerMultiStateButton (parentWidget, 
                            id, 
                            wx.DefaultPosition,
                            (self.minimumSize.width, self.minimumSize.height),
                            helpString = self.helpString,
                            multibitmaps=(normal, stamped))

        parentWidget.Bind(wx.EVT_BUTTON, self.buttonPressed, id=id)
        return button

    def isStamped(self):
        stamped = (self.widget.currentState == "%s.Stamped" % self.icon)
        return stamped

class wxChandlerMultiStateButton(MultiStateButton.MultiStateButton):
    """
    Just like MultiStateButton, except that it uses wx.GetApp().GetImage
    as the provider of bitmaps, and the button has no border.
    
    Dispatch notifications at the end of handling the left-up event, because
    we'll destroy the button in the process of stamping, and the base-class
    implementation tries to use it again (to Refresh, etc.)
    """
    def __init__(self, parent, ID, pos, size, multibitmaps, *args, **kwds):
        if kwds.get('bitmapProvider') is None:
            kwds['bitmapProvider'] = wx.GetApp().GetImage
        super(wxChandlerMultiStateButton, self).__init__(parent,
                                                        ID,
                                                        pos,
                                                        size,
                                                        wx.BORDER_NONE,
                                                        multibitmaps = multibitmaps,
                                                        *args, **kwds)
    def AcceptsFocus(self):
        return False

    def OnLeftUp(self, event):
        if not self.IsEnabled() or not self.HasCapture():
            return
        if self.HasCapture():
            self.ReleaseMouse()
            if not self.up:    # if the button was down when the mouse was released...
                # use wx.CallAfter() in case the button is deleted
                wx.CallAfter(self.Notify)
            self.up = True
            self.Refresh()
            event.Skip()


class textStyleEnumType(schema.Enumeration):
      values = "PlainText", "RichText"


class EditText(RectangularChild):

    characterStyle = schema.One(Styles.CharacterStyle)
    lineStyleEnum = schema.One(lineStyleEnumType)
    textStyleEnum = schema.One(textStyleEnumType, initialValue = 'PlainText')
    readOnly = schema.One(schema.Boolean, initialValue = False)
    textAlignmentEnum = schema.One(
        textAlignmentEnumType, initialValue = 'Left',
    )
    schema.addClouds(
        copying = schema.Cloud(byRef=[characterStyle])
    )

    def instantiateWidget(self):
        # Remove STATIC_BORDER: it wrecks padding on WinXP; was: style = wx.STATIC_BORDER
        style = 0
        if self.textAlignmentEnum == "Left":
            style |= wx.TE_LEFT
        elif self.textAlignmentEnum == "Center":
            style |= wx.TE_CENTRE
        elif self.textAlignmentEnum == "Right":
            style |= wx.TE_RIGHT

        if self.lineStyleEnum == "MultiLine":
            style |= wx.TE_MULTILINE
        else:
            style |= wx.TE_PROCESS_ENTER

        if self.textStyleEnum == "RichText":
            style |= wx.TE_RICH2

        if self.readOnly:
            style |= wx.TE_READONLY

        editText = AttributeEditors.wxEditText (self.parentBlock.widget,
                               -1,
                               "",
                               wx.DefaultPosition,
                               (self.minimumSize.width, self.minimumSize.height),
                               style=style, name=self.itsUUID.str64())

        editText.SetFont(Styles.getFont(getattr(self, "characterStyle", None)))
        return editText

class HtmlWindowWithStatus(wxHtml.HtmlWindow):
    def __init__(self, *arguments, **keywords):
        super (HtmlWindowWithStatus, self).__init__ (*arguments, **keywords)
        # The default setting is to show link URLs in the statusbar of the mainframe.
        self.showMessagesInStatusbar(wx.GetApp().mainFrame, True)
        
    def showMessagesInStatusbar(self, relatedFrame, show):
        self.SetRelatedFrame(relatedFrame, u"%s")
        if show:
            self.SetRelatedStatusBar(0)
        else:
            self.SetRelatedStatusBar(-1)
        
    def OnSetTitle(self, title):
        # This is an empty handler for setting the main frame window title.
        # It is empty because we do not want to show the current URL in main frame window title.
        pass
    
class wxHTML(BaseWidget, HtmlWindowWithStatus):
    def OnLinkClicked(self, link):
        webbrowser.open(link.GetHref())

    def wxSynchronizeWidget(self):
        super (wxHTML, self).wxSynchronizeWidget()
        if self.IsShown():
            text = self.blockItem.text
            if self.blockItem.treatTextAsURL:
                self.LoadPage (text)
            else:
                self.SetPage (text)

class HTML(RectangularChild):
    text = schema.One(schema.Text)
    treatTextAsURL = schema.One(schema.Boolean, defaultValue = False)

    def instantiateWidget (self):
       return wxHTML (self.parentBlock.widget,
                      self.getWidgetID(),
                      wx.DefaultPosition,
                      (self.minimumSize.width, self.minimumSize.height))

    def onSetContentsEvent(self, event):
        self.setContentsOnBlock(event.arguments['item'],
                                event.arguments['collection'])
        widget = getattr (self, "widget", None)
        if widget is not None:
            widget.wxSynchronizeWidget()

class columnType(schema.Enumeration):
    """
    Indicates the type of the value used in the column, that
    determines the way that attributeName or stamp is used

    An 'attribute' column gets the value of the item using
    attributeName as the attribute name.

    A 'stamp' column gets the value of the item passing stamp
    to the attribute editor.
    """
    values = 'attribute', 'stamp', 'None'


class Column(schema.Item):

    heading = schema.One(LocalizableString, defaultValue="")

    valueType = schema.One(columnType, initialValue='attribute',
                           doc="The type of value being displayed in "
                           "this column. Determines if client code "
                           "should use 'attributeName' or 'kind' "
                           "attributes of the Column object when "
                           "determining the value of the item in "
                           "this column")

    attributeName = schema.One(schema.Importable,
                               doc="The attribute used to "
                               "evaluate the column value for the "
                               "item in the row.")
    
    attributeSourceName = schema.One(schema.Importable,
                                     doc="The origin of the value used for "
                                     "this attribute in this row.")
    
    indexName = schema.One(schema.Importable, defaultValue="__adhoc__",
                           doc="The name of the IndexDefinition we'll use to "
                           "order this column")

    icon = schema.One(schema.Text, 
                      doc="An optional name of an image to "
                      "display instead of a label")
    
    format = schema.One(schema.Text,
                        doc="Optional influence for the attribute editor "
                            "used to present cells in this column")
    
    useSortArrows = schema.One(schema.Boolean, defaultValue=True,
                               doc="Show arrows when sorting by this column?")
    
    stamp = schema.One(schema.Class, doc="The pim.Stamp class "
                      "for 'stamp' columns")

    width = schema.One(schema.Integer,  defaultValue = 20,
                       doc="The width of the column, "
                       "relative to other columns")

    scaleColumn = schema.One(schema.Integer, defaultValue = wxGrid.Grid.GRID_COLUMN_NON_SCALABLE)
    readOnly = schema.One(schema.Boolean, initialValue=False)
    defaultSort = schema.One(schema.Boolean, initialValue=False)
    collapsedSections = schema.Many(schema.Text, initialValue=set())
      
    schema.addClouds(
        copying = schema.Cloud(byRef=[stamp],
                               byCloud=[collapsedSections])
    )

    def getAttributeEditorValue(self):
        if self.valueType == 'stamp':
            return self.stamp
        elif self.valueType == 'None':
            return "None"
        else:
            return self.attributeName
        
    def isSectionCollapsed(self, sectionValue):
        return str(sectionValue) in self.collapsedSections
    
    def setSectionState(self, sectionValue, collapsed):
        valueStr = str(sectionValue)
        if collapsed:
            assert valueStr not in self.collapsedSections
            self.collapsedSections.add(valueStr)
        else:
            assert valueStr in self.collapsedSections
            self.collapsedSections.remove(valueStr)
        
    def getWidth(self):
        return self.width

class ListDelegate (object):
    """
    Default delegate for Lists that use the block's contents.

    Override to customize your behavior. You must implement
    GetElementValue.
    """
    def GetColumnCount (self):
        return len (self.blockItem.columns)

    def GetElementCount (self):
        return len (self.blockItem.contents)

    def GetElementType (self, row, column):
        return "Text"

    def GetColumnHeading (self, column, item):
        return self.blockItem.columns[column].heading

    def ReadOnly (self, row, column):
        """
        Second argument should be C{True} if all cells have the first value.
        """
        return False, True

    def RowToIndex(self, tableRow):
        """
        Translates a UI row, such as row 3 in the grid, to the
        appropriate row in the collection.
        """
        return tableRow

    def IndexToRow(self, itemIndex):
        """
        Translates an item index, such as item 3 in the collection,
        into a row in the table.
        """
        return itemIndex

    def RangeToIndex(self, startRow, endRow):
        """
        Translasted a row range in the grid to a row range in the collection
        """
        return self.RowToIndex(startRow), self.RowToIndex(endRow)

    def InitElementDelegate(self):
        """
        Called right after the delegate has been mixed in.
        """
        pass
    
    def SynchronizeDelegate(self):
        """
        Companion to wxSynchronizeWidget - gets called after the main
        class has synchronized itself.
        """
        pass


class AttributeDelegate (ListDelegate):
    """
    Overrides certain methods of wx.grid.Grid.
    """
    def GetElementType (self, row, column):
        """
        An apparent bug in wxWidgets occurs when there are no items
        in a table, the Table asks for the type of cell 0,0
        """
        typeName = "_default"
        try:
            itemIndex = self.RowToIndex(row)
            assert itemIndex != -1
            
            item = self.blockItem.contents [itemIndex]
        except IndexError:
            pass
        else:
            col = self.blockItem.columns[column]
            
            if col.valueType == 'stamp':
                typeName = col.stamp.__name__ # ?
                
            elif col.valueType == 'None':
                typeName = "None"

            elif col.valueType == 'attribute':
                attributeName = col.attributeName
                if item.itsKind.hasAttribute(attributeName):
                    try:
                        typeName = item.getAttributeAspect (attributeName, 'type').itsName
                    except NoSuchAttributeError:
                        # We special-case the non-Chandler attributes we
                        # want to use (_after_ trying the Chandler
                        # attribute, to avoid a hit on Chandler-attribute
                        # performance). If we want to add other
                        # itsKind-like non-Chandler attributes, we'd add
                        # more tests here.
                        raise
                elif attributeName == 'itsKind':
                    typeName = 'Kind'
                else:
                    # Is it a Calculated?
                    descriptor = getattr(item.__class__, attributeName, None)
                    calculatedType = getattr(descriptor, 'type', None)
                    if calculatedType is not None:
                        # It's a Calculated - use the type name
                        typeName = calculatedType.__name__
            else:
                try:
                    # to support properties, we get the value, and use its type's name.
                    value = getattr (item, attributeName)
                except AttributeError:
                    pass
                else:
                    typeName = type (value).__name__
            format = getattr(col, 'format', None)
            if format is not None:
                typeName = "%s+%s" % (typeName, format)
        return typeName

    def GetElementValue (self, row, column):
        itemIndex = self.RowToIndex(row)
        assert itemIndex != -1

        blockItem = self.blockItem
        item = blockItem.contents[itemIndex]
        col = blockItem.columns[column]
        
        return (item, col.getAttributeEditorValue())
    
    def SetElementValue (self, row, column, value):
        itemIndex = self.RowToIndex(row)
        assert itemIndex != -1
        
        # just for now, you can't 'set' a stamp
        assert self.blockItem.columns[column].valueType != 'stamp'
        
        item = self.blockItem.contents [itemIndex]
        attributeName = self.blockItem.columns[column].attributeName
        assert item.itsKind.hasAttribute (attributeName), "You cannot set a non-Chandler attribute value of an item (like itsKind)"
        setattr(item, attributeName, value)

    def GetColumnHeading (self, column, item):
        col = self.blockItem.columns[column]
        heading = col.heading
        
        # Add the attribute source name to the header, if we have one.
        # ** Don't do this: it's not localizable and often clipped: bug 10134.
        #if col.valueType != 'stamp':
            #attributeSourceName = getattr(col, 'attributeSourceName', None)
            #if attributeSourceName is not None:
                #actual = getattr(item, attributeSourceName, None)
                #if actual:
                    ## actual can't be None or ""
                    #heading = _(u"%(heading)s (%(actual)s)") % {
                        #'heading': heading, 'actual': actual }
        return heading

class wxList (DragAndDrop.DraggableWidget, 
              DragAndDrop.ItemClipboardHandler,
              wx.ListCtrl):
    def __init__(self, *arguments, **keywords):
        super (wxList, self).__init__ (*arguments, **keywords)
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnWXSelectItem, id=self.GetId())
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self.OnItemDrag)

    def OnInit (self):
        elementDelegate = self.blockItem.elementDelegate
        if not elementDelegate:
            elementDelegate = 'osaf.framework.blocks.ControlBlocks.ListDelegate'
        mixinAClass (self, elementDelegate)

    @WithoutSynchronizeWidget
    def OnSize(self, event):
        size = self.GetClientSize()
        widthMinusLastColumn = 0
        assert self.GetColumnCount() > 0, "We're assuming that there is at least one column"
        for column in xrange (self.GetColumnCount() - 1):
            widthMinusLastColumn += self.GetColumnWidth (column)
        lastColumnWidth = size.width - widthMinusLastColumn
        if lastColumnWidth > 0:
            self.SetColumnWidth (self.GetColumnCount() - 1, lastColumnWidth)
        event.Skip()

    @WithoutSynchronizeWidget
    def OnWXSelectItem(self, event):
        item = self.blockItem.contents [event.GetIndex()]
        if self.blockItem.selection != item:
            self.blockItem.selection = item
        self.blockItem.postEventByName("SelectItemsBroadcast", {'items':[item]})
        event.Skip()

    def OnItemDrag(self, event):
        self.DoDragAndDrop()

    def SelectedItems(self):
        """
        Return the list of items currently selected.
        """
        curIndex = -1
        while True:
            curIndex = self.GetNextItem(curIndex, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
            yield self.blockItem.contents [curIndex]
            if curIndex is -1:
                break

    def wxSynchronizeWidget(self):
        self.Freeze()
        self.ClearAll()
        self.SetItemCount (self.GetElementCount())
        for columnIndex in xrange (self.GetColumnCount()):
            self.InsertColumn (columnIndex,
                               self.GetColumnHeading (columnIndex, self.blockItem.selection),
                               width = self.blockItem.columns[columnIndex].width)

        self.Thaw()

        if self.blockItem.selection:
            self.GoToItem (self.blockItem.selection)

    def OnGetItemText (self, row, column):
        """
        OnGetItemText won't be called if it's in the delegate -- wxPython
        won't call it if it's in a base class.
        """
        return self.GetElementValue (row, column)

    def OnGetItemImage (self, item):
        return -1

    def GoToItem(self, item):
        self.Select (self.blockItem.contents.index (item))


class wxStaticText(BaseWidget, wx.StaticText):
    pass

class StaticText(RectangularChild):

    textAlignmentEnum = schema.One(
        textAlignmentEnumType, initialValue = 'Left',
    )
    characterStyle = schema.One(Styles.CharacterStyle)
    title = schema.One(LocalizableString)

    schema.addClouds(
        copying = schema.Cloud(byRef=[characterStyle])
    )

    def instantiateWidget (self):
        if self.textAlignmentEnum == "Left":
            style = wx.ALIGN_LEFT
        elif self.textAlignmentEnum == "Center":
            style = wx.ALIGN_CENTRE | wx.ST_NO_AUTORESIZE
        elif self.textAlignmentEnum == "Right":
            style = wx.ALIGN_RIGHT | wx.ST_NO_AUTORESIZE

        if Block.showBorders:
            style |= wx.SIMPLE_BORDER

        staticText = wxStaticText (self.parentBlock.widget,
                                   -1,
                                   self.title,
                                   wx.DefaultPosition,
                                   (self.minimumSize.width, self.minimumSize.height),
                                   style)
        staticText.SetFont(Styles.getFont(getattr(self, "characterStyle", None)))
        return staticText

    
class wxStatusBar (BaseWidget, wx.StatusBar):
    def __init__(self, *arguments, **keyWords):
        super (wxStatusBar, self).__init__ (*arguments, **keyWords)
        self.gauge = wx.Gauge(self, -1, 100, size=(125, 30), style=wx.GA_HORIZONTAL|wx.GA_SMOOTH)
        self.gauge.Show(False)

    def Destroy(self):
        self.blockItem.getFrame().SetStatusBar(None)
        super (wxStatusBar, self).Destroy()
        
    def wxSynchronizeWidget(self):
        super (wxStatusBar, self).wxSynchronizeWidget()
        self.blockItem.getFrame().Layout()


class StatusBar(Block):
    def instantiateWidget (self):
        frame = self.getFrame()
        widget = wxStatusBar (frame, self.getWidgetID())
        frame.SetStatusBar (widget)
        return widget

    def setStatusMessage(self, statusMessage, progressPercentage=-1):
        """
        Allows you to set the message contained in the status bar.
        You can also specify values for the progress bar contained on
        the right side of the status bar.  If you specify a
        progressPercentage (as a float 0 to 1) the progress bar will appear.
        If no percentage is specified the progress bar will disappear.
        """
        if progressPercentage == -1:
            if self.widget.GetFieldsCount() != 1:
                self.widget.SetFieldsCount(1)
            self.widget.SetStatusText(statusMessage)
            self.widget.gauge.Show(False)
        else:
            if self.widget.GetFieldsCount() != 2:
                self.widget.SetFieldsCount(2)
                self.widget.SetStatusWidths([-1, 150])
            if statusMessage is not None:
                self.widget.SetStatusText(statusMessage)
            self.widget.gauge.Show(True)
            self.widget.gauge.SetValue((int)(progressPercentage*100))
            # By default widgets are added to the left side...we must reposition them
            rect = self.widget.GetFieldRect(1)
            self.widget.gauge.SetPosition((rect.x+2, rect.y+2))
                            
"""
    To use the TreeAndList you must provide a delegate to perform access
    to the data that is displayed.

    You might be able to subclass ListDelegate and implement the
    following methods::

        class TreeAndListDelegate (ListDelegate):

        def GetElementParent(self, element):

        def GetElementChildren(self, element):

        def GetElementValues(self, element):

        def ElementHasChildren(self, element):

    Optionally override GetColumnCount and GetColumnHeading.
"""


class wxTreeAndList(DragAndDrop.DraggableWidget, DragAndDrop.ItemClipboardHandler):
    def __init__(self, *arguments, **keywords):
        super (wxTreeAndList, self).__init__ (*arguments, **keywords)
        self.Bind(wx.EVT_TREE_ITEM_EXPANDING, self.OnExpanding, id=self.GetId())
        self.Bind(wx.EVT_TREE_ITEM_COLLAPSING, self.OnCollapsing, id=self.GetId())
        self.Bind(wx.EVT_LIST_COL_END_DRAG, self.OnColumnDrag, id=self.GetId())
        self.Bind(wx.EVT_TREE_SEL_CHANGED, self.OnWXSelectItem, id=self.GetId())
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(wx.EVT_TREE_BEGIN_DRAG, self.OnItemDrag)

    def OnInit (self):
        mixinAClass (self, self.blockItem.elementDelegate)
        
    @WithoutSynchronizeWidget
    def OnSize(self, event):
        if isinstance (self, wxGizmos.TreeListCtrl):
            size = self.GetClientSize()
            widthMinusLastColumn = 0
            assert self.GetColumnCount() > 0, "We're assuming that there is at least one column"
            for column in xrange (self.GetColumnCount() - 1):
                widthMinusLastColumn += self.GetColumnWidth (column)
            lastColumnWidth = size.width - widthMinusLastColumn
            if lastColumnWidth > 0:
                self.SetColumnWidth (self.GetColumnCount() - 1, lastColumnWidth)
        else:
            assert isinstance (self, wx.TreeCtrl), "We're assuming the only other choice is a wx.Tree"
        event.Skip()

    @WithoutSynchronizeWidget
    def OnExpanding(self, event):
        self.LoadChildren(event.GetItem())

    def LoadChildren(self, parentId):
        """
        Load the items in the tree only when they are visible.
        """
        child, cookie = self.GetFirstChild (parentId)
        if not child.IsOk():

            parentUUID = self.GetItemData(parentId).GetData()

            if parentUUID is None:
                parent = None
            else:
                parent = wx.GetApp().UIRepositoryView [parentUUID]

            for child in self.GetElementChildren (parent):
                cellValues = self.GetElementValues (child)
                childNodeId = self.AppendItem (parentId,
                                               cellValues.pop(0),
                                               -1,
                                               -1,
                                               wx.TreeItemData (child.itsUUID))
                index = 1
                for value in cellValues:
                    self.SetItemText (childNodeId, value, index)
                    index += 1
                self.SetItemHasChildren (childNodeId, self.ElementHasChildren (child))
 
            self.blockItem.openedContainers [parentUUID] = True

    def OnCollapsing(self, event):
        id = event.GetItem()
        """
        If the data passed in has a UUID we'll keep track of the
        state of the opened tree.
        """
        del self.blockItem.openedContainers [self.GetItemData(id).GetData()]
        self.DeleteChildren (id)

    @WithoutSynchronizeWidget
    def OnColumnDrag(self, event):
        columnIndex = event.GetColumn()
        try:
            self.blockItem.columns[columnIndex].width = self.GetColumnWidth (columnIndex)
        except AttributeError:
            pass

    @WithoutSynchronizeWidget
    def OnWXSelectItem(self, event):
    
        itemUUID = self.GetItemData(self.GetSelection()).GetData()
        selection = self.blockItem.find (itemUUID)
        if self.blockItem.selection != selection:
            self.blockItem.selection = selection

            self.blockItem.postEventByName("SelectItemsBroadcast",
                                           {'items':[selection]})
        event.Skip()
        
    def SelectedItems(self):
        """
        Return the list of selected items.
        """
        try:
            idList = self.GetSelections() # multi-select API supported?
        except:
            idList = [self.GetSelection(), ] # use single-select API
        # convert from ids, which are UUIDs, to items.
        for id in idList:
            itemUUID = self.GetItemData(id).GetData()
            yield self.blockItem.findUUID(itemUUID)

    def OnItemDrag(self, event):
        self.DoDragAndDrop()
        
    def wxSynchronizeWidget(self):
        def ExpandContainer (self, openedContainers, id):
            try:
                expand = openedContainers [self.GetItemData(id).GetData()]
            except KeyError:
                pass
            else:
                self.LoadChildren(id)

                self.Expand(id)

                child, cookie = self.GetFirstChild (id)
                while child.IsOk():
                    ExpandContainer (self, openedContainers, child)
                    child = self.GetNextSibling (child)

        # A wx.TreeCtrl won't use columns
        columns = getattr (self.blockItem, 'columns', None);
        if columns is not None:
            for index in xrange(wxGizmos.TreeListCtrl.GetColumnCount(self)):
                self.RemoveColumn (0)
    
            info = wxGizmos.TreeListColumnInfo()
            for index in xrange (self.GetColumnCount()):
                info.SetText (self.GetColumnHeading (index, None))
                info.SetWidth (columns[index].width)
                self.AddColumnInfo (info)

        self.DeleteAllItems()

        root = self.blockItem.rootPath
        if root is None:
            root = self.GetElementChildren (None)[0]
        cellValues = self.GetElementValues (root)
        itemData = wx.TreeItemData (root.itsUUID)
        rootNodeId = self.AddRoot (cellValues.pop(0), -1, -1, itemData)        
        index = 1
        for value in cellValues:
            self.SetItemText (rootNodeId, value, index)
            index += 1
        self.SetItemHasChildren (rootNodeId, self.ElementHasChildren (root))
        self.LoadChildren (rootNodeId)
        ExpandContainer (self, self.blockItem.openedContainers, rootNodeId)

        selection = self.blockItem.selection
        if not selection:
            selection = root
        self.GoToItem (selection)
        
    def GoToItem(self, item):
        def ExpandTreeToItem (self, item):
            parent = self.GetElementParent (item)
            if parent:
                id = ExpandTreeToItem (self, parent)
                self.LoadChildren(id)
                if self.IsVisible(id):
                    self.Expand (id)
                itemUUID = item.itsUUID
                child, cookie = self.GetFirstChild (id)
                while child.IsOk():
                    if self.GetItemData(child).GetData() == itemUUID:
                        return child
                    child = self.GetNextSibling (child)
                assert False, "Didn't find the item in the tree"
                return None
            else:
                return self.GetRootItem()

        id = ExpandTreeToItem (self, item)
        self.SelectItem (id)
        self.ScrollTo (id)

    @classmethod
    def CalculateWXStyle(theClass, block):
        style = wx.TR_DEFAULT_STYLE|wx.NO_BORDER
        if block.hideRoot:
            style |= wx.TR_HIDE_ROOT
        if block.noLines:
            style |= wx.TR_NO_LINES
        if block.useButtons:
            style |= wx.TR_HAS_BUTTONS
        else:
            style |= wx.TR_NO_BUTTONS
        return style
        
 
class wxTree(wxTreeAndList, wx.TreeCtrl):
    pass
    

class wxTreeList(wxTreeAndList, wxGizmos.TreeListCtrl):
    pass


class Tree(RectangularChild):

    columns = schema.Sequence(Column)

    # We currently use Tree to display the repository in the
    # RepositoryViewer. Since Items in the repository may not
    # have Kinds and we want to store them in the selection,
    # we can't specify a kind for the selection. To be consistent
    # we'll treat rootPath the same way.
    elementDelegate = schema.One(schema.Text, initialValue = '')
    selection = schema.One(initialValue = None)
    hideRoot = schema.One(schema.Boolean, initialValue = True)
    noLines = schema.One(schema.Boolean, initialValue = True)
    useButtons = schema.One(schema.Boolean, initialValue = True)
    openedContainers = schema.Mapping(schema.Boolean, initialValue = {})
    rootPath = schema.One(initialValue = None)

    schema.addClouds(
        copying = schema.Cloud(byCloud=[selection, columns])
    )

    def instantiateWidget(self):
        try:
            self.columns
        except AttributeError:
            tree = wxTree (self.parentBlock.widget, self.getWidgetID(), 
                           style=wxTreeAndList.CalculateWXStyle(self))
        else:
            tree = wxTreeList (self.parentBlock.widget, self.getWidgetID(), 
                               style=wxTreeAndList.CalculateWXStyle(self))
        return tree

    def onSelectItemsEvent (self, event):
        items = event.arguments['items']
        if len(items)>0:
            self.widget.GoToItem (event.arguments['items'][0])


class wxItemDetail(HtmlWindowWithStatus):
    def OnLinkClicked(self, wx_linkinfo):
        """
        Clicking on an item changes the selection (post event).
        Clicking on a URL loads the page in a separate browser.
        """
        itemURL = wx_linkinfo.GetHref()
        item = self.blockItem.findPath(itemURL)
        if not item:
            webbrowser.open(itemURL)
        else:
            self.blockItem.postEventByName("SelectItemsBroadcast",
                                           {'items':[item]})

    def wxSynchronizeWidget(self):
        blockItem = self.blockItem
        item = getattr (blockItem, "contents",getattr (blockItem, "selection", None))
        if item is not None:
            self.SetPage (blockItem.getHTMLText (item))
        else:
            self.SetPage('<html><body></body></html>')


class ItemDetail(RectangularChild):

    # We currently use ItemDetail to display the repository in the
    # RepositoryViewer. Since Items in the repository may not
    # have Kinds and we want to store them in the selection,
    selection = schema.One(initialValue = None)
    schema.addClouds(
        copying = schema.Cloud(byRef=[selection])
    )

    def instantiateWidget (self):
        return wxItemDetail (self.parentBlock.widget,
                             self.getWidgetID(),
                             wx.DefaultPosition,
                             (self.size.width,
                              self.size.height))

    def getHTMLText(self, item):
        return u'<body><html><h1>%s</h1></body></html>' % item.getDisplayName()

    def onSelectItemsEvent (self, event):
        """
        Display the item in the wxWidget.
        """
        items = event.arguments['items']
        if len(items)>0:
            self.selection = items[0]
        else:
            self.selection = None
        self.synchronizeWidget ()


class ContentItemDetail(BoxContainer):
    """
    Any container block in the Content Item's Detail View hierarchy.

    Not to be confused with ItemDetail (above) which uses an HTML-based widget.
    Keeps track of the current selected item supports Color Style.
    """
    colorStyle = schema.One(Styles.ColorStyle)

class wxPyTimer(wx.Timer):
    """ 
    A wx.PyTimer that has an IsShown() method, like all the other widgets
    that blocks deal with; it also generates its own event from Notify.
    """
    
    def IsShown(self):
        return True

    def Notify(self):
        event = wx.PyEvent()
        event.SetEventType(wx.wxEVT_TIMER)
        event.SetId(self.GetId())
        wx.GetApp().OnCommand(event)

    def Destroy(self):
        Block.wxOnDestroyWidget(self)

class wxThreadingTimer(wxPyTimer):
    """ 
    A wxPyTimer subclass that implements its delay via threading.Timer.
    This turns out to be more reliable on the Mac than wx.PyTimer; its
    implementation can get badly confused by sleep/wake [Bug 9109]
    
    @ivar timerThread: The C{threading.Timer} object used to implement the
                       delay. This is actually a property that ensures that
                       the timer is cleaned up properly on Stop() or Destroy()
                       of the widget.
    @type timerThread: L{threading.Timer}

    @cvar _threadDict: Dictionary of C{threading.Timer} objects, keyed by
                       wxThreadingTimer.
    @type _threadDict: dict
    
    """
    
    _threadDict = None

    @staticmethod
    def _cancelThreads(threads):
        for t in threads.values():
            if __debug__:
                logger.debug("wxThreadingTimer<%s> _cancelThreads", id(t))
            t.cancel()
            
        
    def _setTimer(self, threadingTimer):
        if self._threadDict is None:
            # Because of the somewhat abrupt way we exit the wx event loop
            # when quitting Chandler, we need to clean up any pending
            # threading.Timer objects, or you'll get weird errors during
            # interpreter shutdown.
            import atexit
            wxThreadingTimer._threadDict = dict()
            atexit.register(self._cancelThreads, self._threadDict)
        self._cleanupAndDeleteTimer()
        self._threadDict[self] = threadingTimer
        
    def _getTimer(self):
        threadDict = self._threadDict
        return None if threadDict is None else threadDict.get(self, None)
        
    def _cleanupAndDeleteTimer(self):
        if self._threadDict is not None:
            try:
                timer = self._threadDict.pop(self)
            except KeyError:
                pass
            else:
                # It's safe to cancel a threading.Timer multiple times
                timer.cancel()
            
    timerThread = property(fget=_getTimer, fset=_setTimer,
                           fdel=_cleanupAndDeleteTimer)

                  
    def Start(self, milliseconds=-1, oneShot=False):
        assert oneShot, "Repeating wxThreadingTimers are not supported"
            
        if __debug__:
            logger.debug("wxThreadingTimer<%s>.Start(%s, %s)",
                         id(self.timerThread), milliseconds, oneShot)

        self.timerThread = threading.Timer(float(milliseconds)/1000.0,
                                           self._Notify)
        self.timerThread.setDaemon(True) # let main thread exit even if running
        self.timerThread.start()
        
    def Stop(self, *args, **kw):
        if __debug__:
            logger.debug("wxThreadingTimer<%s>.Stop()", id(self.timerThread))
        del self.timerThread
            
    def _Notify(self):
        if __debug__:
            logger.debug("wxThreadingTimer<%s>._Notify()", id(self.timerThread))
        del self.timerThread
        
        # Due to race conditions, self might have been destroyed at this
        # point    
        if self:
            # Use CallAfter(), or we'll end up posting an event in the
            # wrong thread/at the wrong time.
            wx.CallAfter(self.Notify)

    def Destroy(self):
        if __debug__:
            logger.debug("wxThreadingTimer<%s>.Destroy()", id(self.timerThread))
        del self.timerThread
        return super(wxThreadingTimer, self).Destroy()


class Timer(Block):
    """
    A Timer block. Fires (sending a BlockEvent) at a particular time.
    A passed time will fire "shortly".
    """

    event = schema.One(
        BlockEvent,
        doc = "The event we'll send when we go off",
    )

    schema.addClouds(
        copying = schema.Cloud(byCloud=[event])
    )

    if wx.Platform == '__WXMAC__':
        timerClass = wxThreadingTimer
    else:
        timerClass = wxPyTimer

    def instantiateWidget (self):
        return type(self).timerClass(self.parentBlock.widget,
                                     self.getWidgetID())
        return timer

    def onDestroyWidget(self):
        self.widget.Stop()
        super(Timer, self).onDestroyWidget()

    def setFiringTime(self, when):
        """ 
        Set the timer. 
        "when" can be a timedelta (relative to now) or a datetime (absolute).
        """
        # First turn off the old timer
        timer = self.widget
        timer.Stop()

        # Set the new time, if we have one. If it's in the past, fire "really soon". If it's way in the future,
        # don't bother firing.
        if when is not None:
            view = self.itsView
            if isinstance(when, timedelta):
                td = when
                if __debug__:
                    when = datetime.now(view.tzinfo.default) + when
            else:
                td = (when - datetime.now(view.tzinfo.default))
            millisecondsUntilFiring = (((td.days * 86400) + td.seconds) * 1000L
                                        + td.microseconds // 1000L)
            if millisecondsUntilFiring < 100:
                millisecondsUntilFiring = 100
            elif millisecondsUntilFiring > sys.maxint:
                millisecondsUntilFiring = sys.maxint

            #logger.warning("*** setFiringTime: will fire at %s in %s minutes" 
                         #% (when, millisecondsUntilFiring / 60000))
            timer.Start(millisecondsUntilFiring, True)
        else:
            #logger.warning("*** setFiringTime: No new time.")
            pass

class ReminderTimer(Timer):
    """
    Watches for reminders & drives the reminder dialog.
    """
    
    def synchronizeWidget (self, *args, **kwds):
        #logger.warning("*** Synchronizing ReminderTimer widget!")
        super(ReminderTimer, self).synchronizeWidget(*args, **kwds)
        if not wx.GetApp().ignoreSynchronizeWidget:
            self.primeReminderTimer()
    
    def onReminderTimeEvent(self, event):
        # Run the reminders dialog and re-queue our timer if necessary
        #logger.warning("*** Got reminders time event!")
        self.primeReminderTimer()

    def primeReminderTimer(self):
        """
        Prime the reminder timer and maybe show or hide the dialog
        """
        # Ignore prime calls while we're priming
        if getattr(self, '_inPrimeReminderTimer', False):
            logger.warning("(** skipping recursive call to primeReminderTimer")
            return
        
        view = self.itsView

        self._inPrimeReminderTimer = True
        now = datetime.now(view.tzinfo.default)
        nextReminderItem = None
        
        try:
            mainFrame = wx.GetApp().mainFrame
            if not mainFrame or not mainFrame.IsShown():
                # The main window isn't up yet; try again shortly.
                (nextReminderTime, closeIt) = (now + timedelta(seconds=1), False)
            else:
                # Update triagestatus on each pending reminder. Dismiss any
                # internal reminders that exist only to trigger on startTime.
                pending = Reminder.getPendingTuples(view, now)
                if pending:
                    def processReminder((reminderTime, remindable, reminder)):
                        #logger.warning("*** now-ing %s due to %s", 
                                       #debugName(remindable), reminder)
                        assert not reminder.isDeleted()
                        if reminder.promptUser:
                            return True # this should appear in the list.
                        # This is a non-user reminder, which served only to let us
                        # bump the triageStatus. Discard it.
                        reminder.dismissItem(remindable)
                        return False
                    pending = filter(processReminder, pending)

                # Get the dialog if we have it; we'll create it 
                # if it doesn't exist.
                if pending:
                    reminderDialog = self.getReminderDialog(True)

                    # The dialog is displayed; get the list of pending reminders and 
                    # let it update itself. It'll tell us when it wants us to fire next, 
                    # or whether we should close it now.
                                        
                    (nextReminderTime, nextReminderItem, closeIt) = reminderDialog.UpdateList(pending)
                else:
                    # Or not.
                    (nextReminderTime, nextReminderItem, closeIt) = (None, None, True)
            if nextReminderTime is None:
                # The dialog didn't give us a time to fire; we'll fire at the
                # next non-pending reminder's time.
                reminders = schema.ns('osaf.pim', self.itsView).allFutureReminders
                
                firstReminder = reminders.firstInIndex('reminderPoll')
                while firstReminder is not None:
                    nextReminderTime = firstReminder.nextPoll
                    
                    if nextReminderTime is not None:
                        nextReminderItem = firstReminder.reminderItem
                        break
                         
                     
                    firstReminder.updatePending()
                    firstReminder = reminders.firstInIndex('reminderPoll')

    
            if closeIt:
                self.closeReminderDialog()

            #logger.warning("*** next reminder due %s for %s", 
                           #nextReminderTime, 
                           #debugName(nextReminderItem))
            self.setFiringTime(nextReminderTime)

        finally:
            del self._inPrimeReminderTimer                


    def getReminderDialog(self, createIt):
        try:
            reminderDialog = self.widget.reminderDialog
        except AttributeError:
            if createIt:
                reminderDialog = ReminderDialog.ReminderDialog()
                self.widget.reminderDialog = reminderDialog
                reminderDialog.dismissCallback = self.markDirty
            else:
                reminderDialog = None
        return reminderDialog

    def closeReminderDialog(self):
        try:
            reminderDialog = self.widget.reminderDialog
        except AttributeError:
            pass
        else:
            del self.widget.reminderDialog
            if reminderDialog and not reminderDialog.IsBeingDeleted():
                reminderDialog.Destroy()

class PresentationStyle(schema.Item):
    """ 
    Information that customizes picking or presentation of an attribute
    editor in an L{AEBlock}.

    L{format} is used to influence the picking process; see
    L{osaf.framework.attributeEditors.AttributeEditors.getAEClass} for
    information on how it's used.

    The other settings are used by various attribute editors to customize
    their presentation or behavior.
    """

    sampleText = schema.One(
        LocalizableString,
        doc = 'Localized in-place sample text (optional); if "", will use the attr\'s displayName.',
    )
    format = schema.One(
        schema.Text,
        doc = 'customization of presentation format',
    )
    choices = schema.Sequence(
        LocalizableString,
        doc = 'options for multiple-choice values',
    )
    editInPlace = schema.One(
        schema.Boolean,
        doc = 'For text controls, True if we should wait for a click to become editable',
    )
    lineStyleEnum = schema.One(
        lineStyleEnumType,
        doc = 'SingleLine vs MultiLine for textbox-based editors',
    )
    maxLineCount = schema.One(
        schema.Integer,
        defaultValue = 1,
        doc = """
        The maximum number of lines a text field should temporarily grow to,
        to aid in editing a large amount of text in a small area.
        """,
    )
    schema.addClouds(
        copying = schema.Cloud(
            byValue=[sampleText,format,choices,editInPlace,lineStyleEnum, maxLineCount]
        )
    )

class AEBlock(BoxContainer):
    """
    Attribute Editor Block: instantiates an Attribute Editor appropriate for
    the value of the specified attribute; the Attribute Editor then creates
    the widget. Issues:
     - Finalization.  We're relying on EVT_KILL_FOCUS to know when to end
       editing.  We know the Detail View doesn't always operate in ways that
       cause this to be reliable, but I think these problems can be fixed there.
    """
    schema.kindInfo(
        description="Block that instantiates an appropriate Attribute Editor."
    )

    characterStyle = schema.One(Styles.CharacterStyle, 
        doc="""an optional CharacterStyle in which this editor should draw""")
    readOnly = schema.One(schema.Boolean, initialValue = False,
        doc="If True, this editor should never allow editing of its value, "
            "but may allow selection & copying")
    presentationStyle = schema.One(PresentationStyle,
        doc="""an optional PresentationStyle to customize
               this editor's selection or behavior""")

    schema.addClouds(
        copying = schema.Cloud(byRef=[characterStyle, presentationStyle])
    )

    def setItem(self, value): 
        assert not value.isDeleted()
        self.contents = value
    item = property(Block.getProxiedContents, setItem, 
                    doc="Safely access the selected item (or None)")

    def getAttributeName(self): return getattr(self, 'viewAttribute', None)
    def setAttributeName(self, value): self.viewAttribute = value
    attributeName = property(getAttributeName, setAttributeName, doc=\
                             "Safely access the configured attribute name (or None)")

    def instantiateWidget(self):
        """
        Ask our attribute editor to create a widget for us.

        @return: the widget
        @rtype: wx.Widget
        """
        existingWidget = getattr(self, 'widget', None) 
        if existingWidget is not None:
            return existingWidget

        forEditing = getattr(self, 'forEditing', False)

        # Tell the control what font we expect it to use
        try:
            charStyle = self.characterStyle
        except AttributeError:
            charStyle = None
        font = Styles.getFont(charStyle)

        editor = self.lookupEditor()
        if editor is None:
            assert isDead(self.item)
            widget = wx.Panel(self.parentBlock.widget, self.getWidgetID())
            return widget

        widget = editor.CreateControl(forEditing, editor.readOnly,
                                      self.parentBlock.widget,
                                      self.getWidgetID(), self, font)
        widget.SetName (self.blockName + "AttributeEditor")
        widget.SetFont(font)
        # logger.warning("Instantiated a %s, forEditing = %s" % (widget, forEditing))

        # Cache a little information in the widget.
        widget.editor = editor

        widget.Bind(wx.EVT_KILL_FOCUS, self.onLoseFocusFromWidget)
        widget.Bind(wx.EVT_KEY_UP, self.onKeyUpFromWidget)
        widget.Bind(wx.EVT_LEFT_DOWN, self.onClickFromWidget)

        return widget

    def synchronizeWidget(self):
        """
        Override to call the editor to do the synchronization.
        """
        def BeginEdit():
            editor = self.lookupEditor()
            if editor is not None:
                editor.BeginControlEdit(editor.item, editor.attributeName, self.widget)

        if not wx.GetApp().ignoreSynchronizeWidget:
            IgnoreSynchronizeWidget(True, BeginEdit)


    def onWidgetChangedSize(self):
        """
        Called by our widget when it changes size.
        Presumes that there's an event boundary at the point where
        we need to resynchronize, so it will work with the Detail View.
        """
        evtBoundaryWidget = self.widget
        while evtBoundaryWidget is not None:
            if evtBoundaryWidget.blockItem.eventBoundary:
                break
            evtBoundaryWidget = evtBoundaryWidget.GetParent()
        if evtBoundaryWidget:
            evtBoundaryWidget.blockItem.synchronizeWidget()

    def lookupEditor(self):
        """
        Make sure we've got the right attribute editor for this type.

        @return: The editor to use for the configured item/attributeName, or None
        @rtype: BaseAttributeEditor
        """
        item = self.item
        if item is None:
            return None
        
        # Get the parameters we'll use to pick an editor
        (typeName, cardinality) = self.getItemAttributeTypeInfo()
        attributeName = self.attributeName
        readOnly = self.isReadOnly(item, attributeName)
        try:
            presentationStyle = self.presentationStyle
        except AttributeError:
            presentationStyle = None
        
        # If we have an editor already, and it's the right one, return it.
        try:
            oldEditor = self.widget.editor
        except AttributeError:
            pass
        else:
            if (oldEditor is not None):
                if (oldEditor.typeName == typeName
                   and oldEditor.cardinality == cardinality
                   and oldEditor.attributeName == attributeName
                   # see bug 4553 note below: was "and oldEditor.readOnly == readOnly"
                   and oldEditor.presentationStyle is presentationStyle):
                    # Yep, it's good enough - use it.
                    oldEditor.item = item # note that the item may have changed.
                    return oldEditor

                # It's not good enough, so we'll be changing editors.
                # unRender(), then re-render(); lookupEditor will get called
                # from within render() and will install the right editor; once
                # it returns, we can just return that.
                # @@@ Note:
                # - I don't know of a case where this can happen now (it would
                #   require a contentitem kind containing an attribute whose
                #   value could have different types, and whose different types
                #   have different attribute editors registered for them), 
                #   so this hasn't been tested.
                # - If this does happen in a situation where this code is called
                #   from within a wx event handler on this item's widget, a
                #   crash would result (because wx won't be happy if we return
                #   through it after that widget has been destroyed).
                # Additional note from work on bug 4553:
                # - Prior to bug 4553, we included read-onlyness in the test 
                #   above for whether the existing editor was still suitable 
                #   for editing this attribute. Unfortunately, that bug
                #   presented a case where this (a need to change widgets, which 
                #   the code below wants to do, but which doesn't work right)
                #   happened. Since this case only happens in 0.6 when readonly-
                #   ness is the issue on text ctrls, I'm fixing the problem by 
                #   making BeginControlEdit on those ctrls call wx.SetEditable
                #   (or not) when appropriate.
                assert False, "Please let Bryan know you've found a case where this happens!"
                logger.warning("AEBlock.lookupEditor %s: Rerendering", 
                             getattr(self, 'blockName', '?'))
                self.unRender()
                self.render()
                self.onWidgetChangedSize(item)
                return getattr(self.widget, 'editor', None)

        # We need a new editor - create one.
        #logger.warning("Creating new AE for %s (%s.%s), ro=%s", 
                     #typeName, item, attributeName, readOnly)
        selectedEditor = AttributeEditors.getInstance(typeName, cardinality,
                            item, attributeName, readOnly, presentationStyle)

        # Note the characteristics that made us pick this editor
        selectedEditor.typeName = typeName
        selectedEditor.cardinality = cardinality
        selectedEditor.item = item
        selectedEditor.attributeName = attributeName
        selectedEditor.readOnly = readOnly
        selectedEditor.presentationStyle = presentationStyle
        selectedEditor.parentBlock = self

        return selectedEditor

    def isReadOnly(self, item, attributeName):
        """
        Are we not supposed to allow editing?

        @param item: The item we're operating on
        @type item: Item
        @param attributeName: the name of the attribute from the item
        @type attributeName: String
        @returns: True if we're configured to be readonly, or if the content
        model says we shouldn't let the user edit this; else False.
        @rtype: Boolean
        """
        if self.readOnly: 
            return True

        # Return true if the domain model says this attribute should be R/O
        # (we might not be editing an item, so we check the method presence)
        try:
            isAttrModifiable = item.isAttributeModifiable
        except AttributeError:
            result = False
        else:
            result = not isAttrModifiable(attributeName)

        #logger.warning("AEBlock: %s %s readonly", attributeName,
                     #result and "is" or "is not")
        return result

    def onSetContentsEvent(self, event):
        self.setContentsOnBlock(event.arguments['item'],
                                event.arguments['collection'])
        assert not hasattr(self, 'widget')

    def getItemAttributeTypeInfo(self):
        """
        Get the type & cardinality of the current attribute.
        
        @returns: A tuple containing the name of the type and the cardinality
        of the item/attribute we're operating on
        @rtype: String
        """
        item = self.item
        if item is None:
            return (None, 'single')

        # Ask the schema for the attribute's type first
        cardinality = 'single'
        theType = item.getAttributeAspect(self.attributeName, 'type', True)
        if theType is not None:
            # The repository knows about it.
            typeName = theType.itsName
            cardinality = item.getAttributeAspect(self.attributeName, 'cardinality')
        else:
            # If the repository doesn't know about it (it might be a property),
            # see if it's one of our type-friendly Calculated properties
            try:
                theType = schema.itemFor(getattr(item.__class__, 
                                                 self.attributeName).type, 
                                         item.itsView)
            except:
                # get its value and use its type
                try:
                    attrValue = getattr(item, self.attributeName)
                except:
                    typeName = "_default"
                else:
                    typeName = type(attrValue).__name__
            else:
                # Got the computed property's type - get its name
                typeName = theType.itsName
        
        return (typeName, cardinality)

    def onClickFromWidget(self, event):
        """
        The widget got clicked on - make sure we're in edit mode.

        @param event: The wx event representing the click
        @type event: wx.Event
        """
        #logger.warning("AEBlock: %s widget got clicked on", self.attributeName)

        # If the widget didn't get focus as a result of the click,
        # grab focus now.
        # @@@ This was an attempt to fix bug 2878 on Mac, which doesn't focus
        # on popups when you click on them (or tab to them!)
        oldFocus = self.getFocusBlock()
        if oldFocus is not self:
            Block.finishEdits(oldFocus) # finish any edits in progress

            #logger.warning("Grabbing focus.")
            wx.Window.SetFocus(self.widget)

        event.Skip()

    def onLoseFocusFromWidget(self, event):
        """
        The widget lost focus - we're finishing editing.

        @param event: The wx event representing the lose-focus event
        @type event: wx.Event
        """
        #logger.warning("AEBlock: %s, widget losing focus" % self.blockName)
        
        if event is not None:
            event.Skip()
        
        # Workaround for wx Mac crash bug, 2857: ignore the event if we're being deleted
        widget = getattr(self, 'widget', None)
        if widget is None or widget.IsBeingDeleted() or widget.GetParent().IsBeingDeleted():
            #logger.warning("AEBlock: skipping onLoseFocus because the widget is being deleted.")
            return

        # Make sure the value is written back to the item. 
        self.saveValue()

    def saveValue(self, commitToo=False, autoSaving=False):
        """
        Make sure the value is written back to the item.
        """
        widget = getattr(self, 'widget', None)
        if widget is not None:
            editor = self.widget.editor
            if (editor is not None) and \
               (((not autoSaving) or editor.IsValidForWriteback(self.widget.GetValue()))):
                editor.EndControlEdit(self.item, self.attributeName, widget)
                if commitToo:
                    self.itsView.commit()
            wx.GetApp().unscheduleSave()

    def unRender(self):
        # Last-chance write-back.
        if getattr(self, 'forEditing', False):
            self.saveValue()
        super(AEBlock, self).unRender()
            
    def onKeyUpFromWidget(self, event):
        if event.m_keyCode == wx.WXK_RETURN \
           and not getattr(event.GetEventObject(), 'ateLastKey', False):
            # Do the tab thing if we're not a multiline thing.
            # stearns says: I think this is wrong (it doesn't mix well when one 
            # of the fields you'd "enter" through is multiline - it clears the 
            # content!) but Mimi wants it to work like iCal.
            try:
                isMultiLine = self.presentationStyle.lineStyleEnum == "MultiLine"
            except AttributeError:
                isMultiLine = False
            if not isMultiLine:
                self.widget.Navigate()
        event.Skip()

# Ewww, yuk.  Blocks and attribute editors are mutually interdependent
import osaf.framework.attributeEditors
AttributeEditors = sys.modules['osaf.framework.attributeEditors']

