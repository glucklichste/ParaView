r"""paraviewweb_protocols is a module that contains a set of ParaViewWeb related
protocols that can be combined together to provide a flexible way to define
very specific web application.
"""

import os, sys, logging, types, inspect, traceback, logging, re, json
from time import time

# import RPC annotation
from autobahn.wamp import exportRpc

# import paraview modules.
import paraview
from paraview import simple, servermanager
from paraview.web import helper
from vtk.web import protocols as vtk_protocols

from vtkWebCorePython import vtkWebInteractionEvent

# Needed for:
#    vtkSMPVRepresentationProxy
#    vtkSMTransferFunctionProxy
#    vtkSMTransferFunctionManager
from vtkPVServerManagerRenderingPython import *

# Needed for:
#    vtkSMProxyManager
from vtkPVServerManagerCorePython import *

# Needed for:
#    vtkDataObject
from vtkCommonDataModelPython import *


# =============================================================================
#
# Base class for any ParaView based protocol
#
# =============================================================================

class ParaViewWebProtocol(vtk_protocols.vtkWebProtocol):

    def __init__(self):
        self.Application = None

    def mapIdToProxy(self, id):
        """
        Maps global-id for a proxy to the proxy instance. May return None if the
        id is not valid.
        """
        id = int(id)
        if id <= 0:
            return None
        return simple.servermanager._getPyProxy(\
                simple.servermanager.ActiveConnection.Session.GetRemoteObject(id))

    def getView(self, vid):
        """
        Returns the view for a given view ID, if vid is None then return the
        current active view.
        :param vid: The view ID
        :type vid: str
        """
        view = self.mapIdToProxy(vid)
        if not view:
            # Use active view is none provided.
            view = simple.GetActiveView()

        if not view:
            raise Exception("no view provided: " + vid)

        return view

# =============================================================================
#
# Handle Mouse interaction on any type of view
#
# =============================================================================

class ParaViewWebMouseHandler(ParaViewWebProtocol):

    @exportRpc("mouseInteraction")
    def mouseInteraction(self, event):
        """
        RPC Callback for mouse interactions.
        """
        view = self.getView(event['view'])

        buttons = 0
        if event["buttonLeft"]:
            buttons |= vtkWebInteractionEvent.LEFT_BUTTON;
        if event["buttonMiddle"]:
            buttons |= vtkWebInteractionEvent.MIDDLE_BUTTON;
        if event["buttonRight"]:
            buttons |= vtkWebInteractionEvent.RIGHT_BUTTON;

        modifiers = 0
        if event["shiftKey"]:
            modifiers |= vtkWebInteractionEvent.SHIFT_KEY
        if event["ctrlKey"]:
            modifiers |= vtkWebInteractionEvent.CTRL_KEY
        if event["altKey"]:
            modifiers |= vtkWebInteractionEvent.ALT_KEY
        if event["metaKey"]:
            modifiers |= vtkWebInteractionEvent.META_KEY

        pvevent = vtkWebInteractionEvent()
        pvevent.SetButtons(buttons)
        pvevent.SetModifiers(modifiers)
        pvevent.SetX(event["x"])
        pvevent.SetY(event["y"])
        #pvevent.SetKeyCode(event["charCode"])
        retVal = self.getApplication().HandleInteractionEvent(view.SMProxy, pvevent)
        del pvevent
        return retVal

# =============================================================================
#
# Basic 3D Viewport API (Camera + Orientation + CenterOfRotation
#
# =============================================================================

class ParaViewWebViewPort(ParaViewWebProtocol):

    @exportRpc("resetCamera")
    def resetCamera(self, view):
        """
        RPC callback to reset camera.
        """
        view = self.getView(view)
        simple.ResetCamera(view)
        try:
            view.CenterOfRotation = view.CameraFocalPoint
        except:
            pass

        self.getApplication().InvalidateCache(view.SMProxy)
        return view.GetGlobalIDAsString()

    @exportRpc("updateOrientationAxesVisibility")
    def updateOrientationAxesVisibility(self, view, showAxis):
        """
        RPC callback to show/hide OrientationAxis.
        """
        view = self.getView(view)
        view.OrientationAxesVisibility = (showAxis if 1 else 0);

        self.getApplication().InvalidateCache(view.SMProxy)
        return view.GetGlobalIDAsString()

    @exportRpc("updateCenterAxesVisibility")
    def updateCenterAxesVisibility(self, view, showAxis):
        """
        RPC callback to show/hide CenterAxesVisibility.
        """
        view = self.getView(view)
        view.CenterAxesVisibility = (showAxis if 1 else 0);

        self.getApplication().InvalidateCache(view.SMProxy)
        return view.GetGlobalIDAsString()

    @exportRpc("updateCamera")
    def updateCamera(self, view_id, focal_point, view_up, position):
        view = self.getView(view_id)

        view.CameraFocalPoint = focal_point
        view.CameraViewUp = view_up
        view.CameraPosition = position
        self.getApplication().InvalidateCache(view.SMProxy)

# =============================================================================
#
# Provide Image delivery mechanism
#
# =============================================================================

class ParaViewWebViewPortImageDelivery(ParaViewWebProtocol):

    @exportRpc("stillRender")
    def stillRender(self, options):
        """
        RPC Callback to render a view and obtain the rendered image.
        """
        beginTime = int(round(time() * 1000))
        view = self.getView(options["view"])
        size = [view.ViewSize[0], view.ViewSize[1]]
        if options and options.has_key("size"):
            size = options["size"]
            view.ViewSize = size
        t = 0
        if options and options.has_key("mtime"):
            t = options["mtime"]
        quality = 100
        if options and options.has_key("quality"):
            quality = options["quality"]
        localTime = 0
        if options and options.has_key("localTime"):
            localTime = options["localTime"]
        reply = {}
        app = self.getApplication()
        reply["image"] = app.StillRenderToString(view.SMProxy, t, quality)
        reply["stale"] = app.GetHasImagesBeingProcessed(view.SMProxy)
        reply["mtime"] = app.GetLastStillRenderToStringMTime()
        reply["size"] = [view.ViewSize[0], view.ViewSize[1]]
        reply["format"] = "jpeg;base64"
        reply["global_id"] = view.GetGlobalIDAsString()
        reply["localTime"] = localTime

        endTime = int(round(time() * 1000))
        reply["workTime"] = (endTime - beginTime)

        return reply


# =============================================================================
#
# Provide Geometry delivery mechanism (WebGL)
#
# =============================================================================

class ParaViewWebViewPortGeometryDelivery(ParaViewWebProtocol):

    @exportRpc("getSceneMetaData")
    def getSceneMetaData(self, view_id):
        view  = self.getView(view_id);
        data = self.getApplication().GetWebGLSceneMetaData(view.SMProxy)
        return data

    @exportRpc("getWebGLData")
    def getWebGLData(self, view_id, object_id, part):
        view  = self.getView(view_id)
        data = self.getApplication().GetWebGLBinaryData(view.SMProxy, str(object_id), part-1)
        return data

# =============================================================================
#
# Time management
#
# =============================================================================

class ParaViewWebTimeHandler(ParaViewWebProtocol):

    def __init__(self):
        super(ParaViewWebTimeHandler, self).__init__()
        # setup animation scene
        self.scene = simple.GetAnimationScene()
        simple.GetTimeTrack()
        self.scene.PlayMode = "Snap To TimeSteps"

    @exportRpc("updateTime")
    def updateTime(self,action):
        view = simple.GetRenderView()
        animationScene = simple.GetAnimationScene()
        currentTime = view.ViewTime

        if action == "next":
            animationScene.GoToNext()
            if currentTime == view.ViewTime:
                animationScene.GoToFirst()
        if action == "prev":
            animationScene.GoToPrevious()
            if currentTime == view.ViewTime:
                animationScene.GoToLast()
        if action == "first":
            animationScene.GoToFirst()
        if action == "last":
            animationScene.GoToLast()

        return view.ViewTime

# =============================================================================
#
# Color management
#
# =============================================================================

class ParaViewWebColorManager(ParaViewWebProtocol):

    def __init__(self, pathToColorMaps=None):
        super(ParaViewWebColorManager, self).__init__()
        self.colorMapNames = []
        if pathToColorMaps is not None:
            self.pathToLuts = pathToColorMaps
        else:
            module_path = os.path.abspath(__file__)
            path = os.path.dirname(module_path)
            self.pathToLuts = os.path.join(path, '..', 'ColorMaps.xml')

    # Rather than keeping a map of these xml strings in memory, it's very
    # quick to just scan the file when we need a color map.  This is a
    # convenience function to read the colormaps file and find the one
    # associated with a particular name, then return it as xml text.  Also
    # builds a list of preset color names and stores them in an instance
    # variable.
    def findColorMapText(self, colorMapName):
        content = None
        self.colorMapNames = []
        with open(self.pathToLuts, 'r') as fd:
            content = fd.read()
            if content is not None:
                colorMapMatcher = re.compile('(<ColorMap.+?(?=</ColorMap>)</ColorMap>)', re.DOTALL)
                nameMatcher = re.compile('name="([^"]+)"')
                iterator = colorMapMatcher.finditer(content)
                for match in iterator:
                    colorMap = match.group(1)
                    m = nameMatcher.search(colorMap)
                    if m:
                        mapName = m.group(1)
                        self.colorMapNames.append(mapName)
                        if mapName == colorMapName:
                            return colorMap

        return None

    @exportRpc("getScalarBarVisibilities")
    def getScalarBarVisibilities(self, proxyIdList):
        """
        Returns whether or not each specified scalar bar is visible.
        """
        visibilities = {}
        for proxyId in proxyIdList:
            proxy = self.mapIdToProxy(proxyId)
            if proxy is not None:
                rep = simple.GetRepresentation(proxy)
                view = self.getView(-1)
                visibilities[proxyId] = vtkSMPVRepresentationProxy.IsScalarBarVisible(rep.SMProxy, view.SMProxy);

        return visibilities

    @exportRpc("setScalarBarVisibilities")
    def setScalarBarVisibilities(self, proxyIdMap):
        """
        Sets the visibility of the scalar bar corresponding to each specified
        proxy.  The representation for each proxy is found using the
        filter/source proxy id and the current view.
        """
        visibilities = {}
        for proxyId in proxyIdMap:
            proxy = self.mapIdToProxy(proxyId)
            if proxy is not None:
                rep = simple.GetDisplayProperties(proxy)
                view = self.getView(-1)
                vtkSMPVRepresentationProxy.SetScalarBarVisibility(rep.SMProxy,
                                                                  view.SMProxy,
                                                                  proxyIdMap[proxyId])
                visibilities[proxyId] = vtkSMPVRepresentationProxy.IsScalarBarVisible(rep.SMProxy,
                                                                                      view.SMProxy);

        return visibilities

    @exportRpc("rescaleTransferFunction")
    def rescaleTransferFunction(self, options):
        """
        Rescale the color transfer function to fit either the data range,
        the data range over time, or to a custom range, for the array by
        which the representation is currently being colored.
        """
        type = options['type']
        proxyId = options['proxyId']
        proxy = helper.idToProxy(proxyId)
        rep = simple.GetRepresentation(proxy)

        status = { 'success': False }

        if type == 'time':
            status['success'] = \
                vtkSMPVRepresentationProxy.RescaleTransferFunctionToDataRangeOverTime(rep.SMProxy)
        elif type == 'data':
            extend = False
            if 'extend' in options:
                extend = options['extend']
            status['success'] = \
                vtkSMPVRepresentationProxy.RescaleTransferFunctionToDataRange(rep.SMProxy, extend)
        elif type == 'custom':
            rangemin = float(options['min'])
            rangemax = float(options['max'])
            extend = False
            if 'extend' in options:
                extend = options['extend']
            lookupTable = rep.LookupTable
            if lookupTable is not None:
                status['success'] = \
                    vtkSMTransferFunctionProxy.RescaleTransferFunction(lookupTable.SMProxy,
                                                                       rangemin,
                                                                       rangemax,
                                                                       extend)

        return status

    @exportRpc("colorBy")
    def colorBy(self, options):
        """
        Choose the array to color by, and optionally specify magnitude or a
        vector component in the case of vector array.
        """
        proxyId = options['proxyId']
        name = options['arrayName']
        attrType = options['attributeType']

        proxy = helper.idToProxy(proxyId)
        dataRepr = simple.GetRepresentation(proxy)

        if attrType == 'POINTS':
            type = vtkDataObject.POINT
        elif attrType == 'CELLS':
            type = vtkDataObject.CELL

        vtkSMPVRepresentationProxy.SetScalarColoring(dataRepr.SMProxy, name, type)

        if 'vectorMode' in options:
            lut = dataRepr.LookupTable
            lut.VectorMode = str(options['vectorMode'])
            if 'vectorComponent' in options:
                lut.VectorComponent = int(options['vectorComponent'])

        # FIXME: This should happen once at the time the lookup table is created
        vtkSMPVRepresentationProxy.RescaleTransferFunctionToDataRange(dataRepr.SMProxy, name, type)

        simple.Render()

    @exportRpc("selectColorMap")
    def selectColorMap(self, options):
        """
        Choose the color map preset to use when coloring by an array.
        """
        proxyId = options['proxyId']
        arrayName = str(options['arrayName'])
        attrType = str(options['attributeType'])
        presetName = str(options['presetName'])

        # First make sure we're coloring by the desired array
        self.colorBy(options)

        proxy = helper.idToProxy(proxyId)
        dataRepr = simple.GetRepresentation(proxy)

        colorMapText = self.findColorMapText(presetName)
        if colorMapText is not None:
            lutProxy = dataRepr.LookupTable
            if lutProxy is not None:
                vtkSMTransferFunctionProxy.ApplyColorMap(lutProxy.SMProxy, colorMapText)
                simple.Render()
                return { 'result': 'success' }
            else:
                return { 'result': 'Representation for proxy ' + proxyId + ' is missing lookup table' }

        return { 'result': 'preset ' + presetName + ' not found' }

    @exportRpc("listColorMapNames")
    def listColorMapNames(self):
        """
        List the names of all color map presets available on the server.  This
        list will contain the names of any presets you provided in the file you
        supplied to the constructor of this protocol.
        """
        self.findColorMapText('')
        return self.colorMapNames


# =============================================================================
#
# Pipeline manager
#
# =============================================================================

class ParaViewWebPipelineManager(ParaViewWebProtocol):

    def __init__(self, baseDir=None, fileToLoad=None):
        super(ParaViewWebPipelineManager, self).__init__()
        # Setup global variables
        self.pipeline = helper.Pipeline('Kitware')
        self.view = simple.GetRenderView()
        self.baseDir = baseDir;
        simple.SetActiveView(self.view)
        simple.Render()
        if fileToLoad and fileToLoad[-5:] != '.pvsm':
            try:
                self.openFile(fileToLoad)
            except:
                print "error loading..."

    def getColorTransferFunction(self, arrayName):
        proxyMgr = vtkSMProxyManager.GetProxyManager()
        sessionProxyMgr = proxyMgr.GetActiveSessionProxyManager()
        lutMgr = vtkSMTransferFunctionManager()
        return lutMgr.GetColorTransferFunction(arrayName, sessionProxyMgr)

    @exportRpc("reloadPipeline")
    def reloadPipeline(self):
        self.pipeline.clear()
        pxm = simple.servermanager.ProxyManager()

        # Fill tree structure (order-less)
        for proxyInfo in pxm.GetProxiesInGroup("sources"):
            id = str(proxyInfo[1])
            proxy = helper.idToProxy(id)
            parentId = helper.getParentProxyId(proxy)
            self.pipeline.addNode(parentId, id)

        return self.pipeline.getRootNode(self.getView(-1))

    @exportRpc("getPipeline")
    def getPipeline(self):
        if self.pipeline.isEmpty():
            return self.reloadPipeline()
        return self.pipeline.getRootNode(self.getView(-1))

    @exportRpc("addSource")
    def addSource(self, algo_name, parent):
        pid = str(parent)
        parentProxy = helper.idToProxy(parent)
        if parentProxy:
            simple.SetActiveSource(parentProxy)
        else:
            pid = '0'

        # Create new source/filter
        cmdLine = 'simple.' + algo_name + '()'
        newProxy = eval(cmdLine)

        # Create its representation and render
        simple.Show()
        simple.Render()
        simple.ResetCamera()

        # Add node to pipeline
        self.pipeline.addNode(pid, newProxy.GetGlobalIDAsString())

        # Handle domains
        helper.apply_domains(parentProxy, newProxy.GetGlobalIDAsString())

        # Return the newly created proxy pipeline node
        return helper.getProxyAsPipelineNode(newProxy.GetGlobalIDAsString(), self.getView(-1))

    @exportRpc("deleteSource")
    def deleteSource(self, proxy_id):
        self.pipeline.removeNode(proxy_id)
        proxy = helper.idToProxy(proxy_id)
        simple.Delete(proxy)
        simple.Render()

    @exportRpc("updateDisplayProperty")
    def updateDisplayProperty(self, options):
        proxy = helper.idToProxy(options['proxy_id'])
        rep = simple.GetDisplayProperties(proxy)
        helper.updateProxyProperties(rep, options)

        if options.has_key('ColorArrayName') and len(options['ColorArrayName']) > 0:
            name = options['ColorArrayName']
            type = options['ColorAttributeType']

            if type == 'POINT_DATA':
                attr_type = vtkDataObject.POINT
            elif type == 'CELL_DATA':
                attr_type = vtkDataObject.CELL

            dataRepr = simple.GetRepresentation(proxy)

            vtkSMPVRepresentationProxy.SetScalarColoring(dataRepr.SMProxy, name, attr_type)
            vtkSMPVRepresentationProxy.RescaleTransferFunctionToDataRange(dataRepr.SMProxy, name, attr_type, True)

        simple.Render()

    @exportRpc("pushState")
    def pushState(self, state):
        proxy_type = None
        for proxy_id in state:
            if proxy_id in ['proxy', 'widget_source']:
                proxy_type = proxy_id
                continue
            proxy = helper.idToProxy(proxy_id);
            helper.updateProxyProperties(proxy, state[proxy_id])
            simple.Render()

        if proxy_type == 'proxy':
            return helper.getProxyAsPipelineNode(state['proxy'], self.getView(-1))
        elif proxy_type == 'widget_source':
            proxy.UpdateWidget(proxy.Observed)

    @exportRpc("openFile")
    def openFile(self, path):
        reader = simple.OpenDataFile(path)
        simple.RenameSource( path.split("/")[-1], reader)
        simple.Show()
        simple.Render()
        simple.ResetCamera()

        # Add node to pipeline
        self.pipeline.addNode('0', reader.GetGlobalIDAsString())

        return helper.getProxyAsPipelineNode(reader.GetGlobalIDAsString(), self.getView(-1))

    @exportRpc("openRelativeFile")
    def openRelativeFile(self, relativePath):
        fileToLoad = []
        if type(relativePath) == list:
            for file in relativePath:
               fileToLoad.append(os.path.join(self.baseDir, file))
        else:
            fileToLoad.append(os.path.join(self.baseDir, relativePath))

        reader = simple.OpenDataFile(fileToLoad)
        name = fileToLoad[0].split("/")[-1]
        if len(name) > 15:
            name = name[:15] + '*'
        simple.RenameSource(name, reader)
        simple.Show()
        simple.Render()
        simple.ResetCamera()

        # Add node to pipeline
        self.pipeline.addNode('0', reader.GetGlobalIDAsString())

        return helper.getProxyAsPipelineNode(reader.GetGlobalIDAsString(), self.getView(-1))

    @exportRpc("updateScalarbarVisibility")
    def updateScalarbarVisibility(self, options):
        lutMgr = vtkSMTransferFunctionManager()
        lutMap = {}
        view = self.getView(-1)
        if options:
            for key, lut in options.iteritems():
                visibility = lut['enabled']
                if type(lut['name']) == unicode:
                    lut['name'] = str(lut['name'])
                parts = key.split('_')
                arrayName = parts[0]
                numComps = int(parts[1])

                lutProxy = self.getColorTransferFunction(arrayName)
                barRep = servermanager._getPyProxy(lutMgr.GetScalarBarRepresentation(lutProxy, view.SMProxy))

                if visibility == 1:
                    barRep.Visibility = 1
                    barRep.Enabled = 1
                    barRep.Title = arrayName
                    if numComps > 1:
                        barRep.ComponentTitle = 'Magnitude'
                    else:
                        barRep.ComponentTitle = ''
                    vtkSMScalarBarWidgetRepresentationProxy.PlaceInView(barRep.SMProxy, view.SMProxy)
                else:
                    barRep.Visibility = 0
                    barRep.Enabled = 0

                lutMap[key] = { 'lutId': lut['name'],
                                        'name': arrayName,
                                        'size': numComps,
                                        'enabled': visibility }
        return lutMap

    @exportRpc("updateScalarRange")
    def updateScalarRange(self, proxyId):
        proxy = self.mapIdToProxy(proxyId);
        dataRepr = simple.GetRepresentation(proxy)
        vtkSMPVRepresentationProxy.RescaleTransferFunctionToDataRange(dataRepr.SMProxy, False)

    @exportRpc("setLutDataRange")
    def setLutDataRange(self, name, number_of_components, customRange):
        lut = self.getColorTransferFunction(name)
        vtkSMTransferFunctionProxy.RescaleTransferFunction(lut, customRange[0],
                                                           customRange[1], False)

    @exportRpc("getLutDataRange")
    def getLutDataRange(self, name, number_of_components):
        lut = self.getColorTransferFunction(name)
        rgbPoints = lut.GetProperty('RGBPoints')
        return [ rgbPoints.GetElement(0),
                 rgbPoints.GetElement(rgbPoints.GetNumberOfElements() - 4) ]


# =============================================================================
#
# Filter list
#
# =============================================================================

class ParaViewWebFilterList(ParaViewWebProtocol):

    def __init__(self, filtersFile=None):
        super(ParaViewWebFilterList, self).__init__()
        self.filterFile = filtersFile

    @exportRpc("listFilters")
    def listFilters(self):
        filterSet = []
        if self.filterFile is None :
            filterSet = [{
                        'name': 'Cone',
                        'icon': 'dataset',
                        'category': 'source'
                    },{
                        'name': 'Sphere',
                        'icon': 'dataset',
                        'category': 'source'
                    },{
                        'name': 'Wavelet',
                        'icon': 'dataset',
                        'category': 'source'
                    },{
                        'name': 'Clip',
                        'icon': 'clip',
                        'category': 'filter'
                    },{
                        'name': 'Slice',
                        'icon': 'slice',
                        'category': 'filter'
                    },{
                        'name': 'Contour',
                        'icon': 'contour',
                        'category': 'filter'
                    },{
                        'name': 'Threshold',
                        'icon': 'threshold',
                        'category': 'filter'
                    },{
                        'name': 'StreamTracer',
                        'icon': 'stream',
                        'category': 'filter'
                    },{
                        'name': 'WarpByScalar',
                        'icon': 'filter',
                        'category': 'filter'
                    }]
        else :
            with open(self.filterFile, 'r') as fd:
                filterSet = json.loads(fd.read())

        if servermanager.ActiveConnection.GetNumberOfDataPartitions() > 1:
            filterSet.append({ 'name': 'D3', 'icon': 'filter', 'category': 'filter' })

        return filterSet


# =============================================================================
#
# Remote file list
#
# =============================================================================

class ParaViewWebFileManager(ParaViewWebProtocol):

    def __init__(self, defaultDirectoryToList):
        super(ParaViewWebFileManager, self).__init__()
        self.directory = defaultDirectoryToList
        self.dirCache = None

    @exportRpc("listFiles")
    def listFiles(self):
        if not self.dirCache:
            self.dirCache = helper.listFiles(self.directory)
        return self.dirCache


# =============================================================================
#
# Handle remote Connection
#
# =============================================================================

class ParaViewWebRemoteConnection(ParaViewWebProtocol):

    @exportRpc("connect")
    def connect(self, options):
        """
        Creates a connection to a remote pvserver.
        Expect an option argument which should override any of
        those default properties::

            {
            'host': 'localhost',
            'port': 11111,
            'rs_host': None,
            'rs_port': 11111
            }

        """
        ds_host = "localhost"
        ds_port = 11111
        rs_host = None
        rs_port = 11111


        if options:
            if options.has_key("host"):
                ds_host = options["host"]
            if options.has_key("port"):
                ds_port = options["port"]
            if options.has_key("rs_host"):
                rs_host = options["rs_host"]
            if options.has_key("rs_port"):
                rs_host = options["rs_port"]

        simple.Connect(ds_host, ds_port, rs_host, rs_port)

    @exportRpc("reverseConnect")
    def reverseConnect(self, port=11111):
        """
        Create a reverse connection to a server.  Listens on port and waits for
        an incoming connection from the server.
        """
        simple.ReverseConnect(port)

    @exportRpc("pvDisconnect")
    def pvDisconnect(self, message):
        """Free the current active session"""
        simple.Disconnect()


# =============================================================================
#
# Handle remote Connection at startup
#
# =============================================================================

class ParaViewWebStartupRemoteConnection(ParaViewWebProtocol):

    connected = False

    def __init__(self, dsHost = None, dsPort = 11111, rsHost=None, rsPort=22222):
        super(ParaViewWebStartupRemoteConnection, self).__init__()
        if not ParaViewWebStartupRemoteConnection.connected and dsHost:
            ParaViewWebStartupRemoteConnection.connected = True
            simple.Connect(dsHost, dsPort, rsHost, rsPort)


# =============================================================================
#
# Handle plugin loading at startup
#
# =============================================================================

class ParaViewWebStartupPluginLoader(ParaViewWebProtocol):

    loaded = False

    def __init__(self, plugins=None, pathSeparator=':'):
        super(ParaViewWebStartupPluginLoader, self).__init__()
        if not ParaViewWebStartupPluginLoader.loaded and plugins:
            ParaViewWebStartupPluginLoader.loaded = True
            for path in plugins.split(pathSeparator):
                simple.LoadPlugin(path, ns=globals())

# =============================================================================
#
# Handle State Loading
#
# =============================================================================

class ParaViewWebStateLoader(ParaViewWebProtocol):

    def __init__(self, state_path = None):
        super(ParaViewWebStateLoader, self).__init__()
        if state_path and state_path[-5:] == '.pvsm':
            self.loadState(state_path)

    @exportRpc("loadState")
    def loadState(self, state_file):
        """
        Load a state file and return the list of view ids
        """
        simple.LoadState(state_file)
        ids = []
        for view in simple.GetRenderViews():
            ids.append(view.GetGlobalIDAsString())
        return ids

# =============================================================================
#
# Handle Server File Listing
#
# =============================================================================

class ParaViewWebFileListing(ParaViewWebProtocol):

    def __init__(self, basePath, name, excludeRegex=r"^\.|~$|^\$", groupRegex=r"[0-9]+\."):
        """
        Configure the way the WebFile browser will expose the server content.
         - basePath: specify the base directory that we should start with
         - name: Name of that base directory that will show up on the web
         - excludeRegex: Regular expression of what should be excluded from the list of files/directories
        """
        self.baseDirectory = basePath
        self.rootName = name
        self.pattern = re.compile(excludeRegex)
        self.gPattern = re.compile(groupRegex)
        pxm = simple.servermanager.ProxyManager()
        self.directory_proxy = pxm.NewProxy('misc', 'ListDirectory')
        self.fileList = simple.servermanager.VectorProperty(self.directory_proxy,self.directory_proxy.GetProperty('FileList'))
        self.directoryList = simple.servermanager.VectorProperty(self.directory_proxy,self.directory_proxy.GetProperty('DirectoryList'))

    @exportRpc("listServerDirectory")
    def listServerDirectory(self, relativeDir='.'):
        """
        RPC Callback to list a server directory relative to the basePath
        provided at start-up.
        """
        path = [ self.rootName ]
        if len(relativeDir) > len(self.rootName):
            relativeDir = relativeDir[len(self.rootName)+1:]
            path += relativeDir.replace('\\','/').split('/')

        currentPath = os.path.join(self.baseDirectory, relativeDir)

        self.directory_proxy.List(currentPath)

        # build file/dir lists
        files = []
        if len(self.fileList) > 1:
            for f in self.fileList.GetData():
                if not re.search(self.pattern, f):
                    files.append( { 'label': f })
        elif len(self.fileList) == 1 and not re.search(self.pattern, self.fileList.GetData()):
            files.append( { 'label': self.fileList.GetData() })

        dirs = []
        if len(self.directoryList) > 1:
            for d in self.directoryList.GetData():
                if not re.search(self.pattern, d):
                    dirs.append(d)
        elif len(self.directoryList) == 1 and not re.search(self.pattern, self.directoryList.GetData()):
            dirs.append(self.directoryList.GetData())

        result =  { 'label': relativeDir, 'files': files, 'dirs': dirs, 'groups': [], 'path': path }
        if relativeDir == '.':
            result['label'] = self.rootName

        # Filter files to create groups
        files.sort()
        groups = result['groups']
        groupIdx = {}
        filesToRemove = []
        for file in files:
            fileSplit = re.split(self.gPattern, file['label'])
            if len(fileSplit) == 2:
                filesToRemove.append(file)
                gName = '*.'.join(fileSplit)
                if groupIdx.has_key(gName):
                    groupIdx[gName]['files'].append(file['label'])
                else:
                    groupIdx[gName] = { 'files' : [file['label']], 'label': gName }
                    groups.append(groupIdx[gName])
        for file in filesToRemove:
            gName = '*.'.join(re.split(self.gPattern, file['label']))
            if len(groupIdx[gName]['files']) > 1:
                files.remove(file)
            else:
                groups.remove(groupIdx[gName])

        return result

# =============================================================================
#
# Handle Data Selection
#
# =============================================================================
from vtkPVClientServerCoreRenderingPython import *
from vtkCommonCorePython import *

class ParaViewWebSelectionHandler(ParaViewWebProtocol):

    def __init__(self):
        self.active_view = None
        self.previous_interaction = -1
        self.selection_type = -1

    @exportRpc("startSelection")
    def startSelection(self, viewId, selectionType):
        """
        Method used to initialize an interactive selection
        """
        self.active_view = self.getView(viewId)
        if self.active_view.IsSelectionAvailable():
            self.previous_interaction = self.active_view.InteractionMode
            self.active_view.InteractionMode = vtkPVRenderView.INTERACTION_MODE_SELECTION
        else:
            self.active_view = None

    @exportRpc("endSelection")
    def endSelection(self, area, extract):
        """
        Method used to finalize an interactive selection by providing
        the [ startPointX, startPointY, endPointX, endPointY ] area
        where (0,0) match the lower left corner of the pixel screen.
        """
        if self.active_view:
            self.active_view.InteractionMode = self.previous_interaction
            representations = vtkCollection()
            sources = vtkCollection()
            if self.selection_type == 0:
                self.active_view.SelectSurfacePoints(area, representations, sources, False)
            elif self.selection_type == 1:
                self.active_view.SelectSurfaceCells(area, representations, sources, False)
            elif self.selection_type == 2:
                self.active_view.SelectFrustumPoints(area, representations, sources, False)
            elif self.selection_type == 3:
                self.active_view.SelectFrustumCells(area, representations, sources, False)
            else:
                self.active_view.SelectSurfacePoints(area, representations, sources, False)
            # Don't know what to do if more than one representation/source
            if representations.GetNumberOfItems() == sources.GetNumberOfItems() and sources.GetNumberOfItems() == 1:
                # We are good for selection
                rep = servermanager._getPyProxy(representations.GetItemAsObject(0))
                selection = servermanager._getPyProxy(sources.GetItemAsObject(0))
                if extract:
                    extract = simple.ExtractSelection(Input=rep.Input, Selection=selection)
                    simple.Show(extract)
                    simple.Render()
                else:
                    rep.Input.SMProxy.SetSelectionInput(0, selection.SMProxy, 0)

# =============================================================================
#
# Handle Data Export
#
# =============================================================================

class ParaViewWebExportData(ParaViewWebProtocol):

    def __init__(self, basePath):
        self.base_export_path = basePath

    @exportRpc("exportData")
    def exportData(self, proxy_id, path):
        proxy = self.mapIdToProxy(proxy_id)
        fullpath = str(os.path.join(self.base_export_path, str(path)))
        if fullpath.index('.vtk') == -1:
            fullpath += '.vtk'
        parentDir = os.path.dirname(fullpath)
        if not os.path.exists(parentDir):
            os.makedirs(parentDir)
        if proxy:
            writer = simple.DataSetWriter(Input=proxy, FileName=fullpath)
            writer.UpdatePipeline()
            del writer

# =============================================================================
#
# Protocols useful only for testing purposes
#
# =============================================================================

class ParaViewWebTestProtocols(ParaViewWebProtocol):

    @exportRpc("clearAll")
    def clearAll(self):
        simple.Disconnect()
        simple.Connect()

    @exportRpc("getColoringInfo")
    def getColoringInfo(self, proxyId):
        proxy = self.mapIdToProxy(proxyId)
        rep = simple.GetRepresentation(proxy)
        lut = rep.LookupTable
        arrayInfo = rep.GetArrayInformationForColorArray()
        arrayName = arrayInfo.GetName()

        return { 'arrayName': arrayName,
                 'vectorMode': lut.VectorMode,
                 'vectorComponent': lut.VectorComponent }


# =============================================================================
#
# Handle Widget Representation
#
# =============================================================================

def _line_update_widget(self, widget):
    widget.Point1WorldPosition = self.Point1;
    widget.Point2WorldPosition = self.Point2;

def _line_widget_update(self, obj, event):
    self.GetProperty('Point1').Copy(obj.GetProperty('Point1WorldPositionInfo'))
    self.GetProperty('Point2').Copy(obj.GetProperty('Point2WorldPositionInfo'))
    self.UpdateVTKObjects()

def _plane_update_widget(self, widget):
    widget.GetProperty('OriginInfo').SetData(self.Origin)
    widget.Origin = self.Origin
    widget.Normal = self.Normal
    widget.UpdateVTKObjects()

def _plane_widget_update(self, obj, event):
    self.GetProperty('Origin').Copy(obj.GetProperty('OriginInfo'))
    self.GetProperty('Normal').Copy(obj.GetProperty('NormalInfo'))
    self.UpdateVTKObjects()
    _hide_plane(obj)

def _draw_plane(obj,event):
    obj.GetProperty('DrawPlane').SetElement(0,1)
    obj.UpdateVTKObjects()

def _hide_plane(obj):
    obj.GetProperty('DrawPlane').SetElement(0,0)
    obj.UpdateVTKObjects()

class ParaViewWebWidgetManager(ParaViewWebProtocol):

    @exportRpc("addRuler")
    def addRuler(self, view_id=-1):
        proxy = simple.Ruler(Point1=[-1.0, -1.0, -1.0], Point2=[1.0, 1.0, 1.0])
        self.createWidgetRepresentation(proxy.GetGlobalID(), view_id)
        return proxy.GetGlobalIDAsString()

    @exportRpc("createWidgetRepresentation")
    def createWidgetRepresentation(self, proxy_id, view_id):
        proxy = self.mapIdToProxy(proxy_id)
        view = self.getView(view_id)
        widgetProxy = None
        # Find the corresponding widget representation
        if proxy.__class__.__name__ == 'Plane':
            widgetProxy = self.CreateWidgetRepresentation(view, 'ImplicitPlaneWidgetRepresentation')
            setattr(proxy.__class__, 'UpdateWidget', _plane_update_widget)
            setattr(proxy.__class__, 'WidgetUpdate', _plane_widget_update)
            widgetProxy.GetProperty('DrawPlane').SetElement(0, 0)
            widgetProxy.GetProperty('PlaceFactor').SetElement(0, 1.0)
            proxy.UpdateWidget(widgetProxy)
            widgetProxy.AddObserver("StartInteractionEvent", _draw_plane)
            proxy.Observed = widgetProxy
            proxy.ObserverTag = widgetProxy.AddObserver("EndInteractionEvent", proxy.WidgetUpdate)
        elif proxy.__class__.__name__ == 'Box':
            widgetProxy = self.CreateWidgetRepresentation(view, 'BoxWidgetRepresentation')
        elif proxy.__class__.__name__ == 'Handle':
            widgetProxy = self.CreateWidgetRepresentation(view, 'HandleWidgetRepresentation')
        elif proxy.__class__.__name__ == 'PointSource':
            widgetProxy = self.CreateWidgetRepresentation(view, 'PointSourceWidgetRepresentation')
        elif proxy.__class__.__name__ == 'LineSource' or proxy.__class__.__name__ == 'HighResolutionLineSource' :
            widgetProxy = self.CreateWidgetRepresentation(view, 'LineSourceWidgetRepresentation')
            setattr(proxy.__class__, 'UpdateWidget', _line_update_widget)
            setattr(proxy.__class__, 'WidgetUpdate', _line_widget_update)
            proxy.UpdateWidget(widgetProxy)
            proxy.Observed = widgetProxy
            proxy.ObserverTag = widgetProxy.AddObserver("EndInteractionEvent", proxy.WidgetUpdate)
        elif proxy.__class__.__name__ == 'Line':
            widgetProxy = self.CreateWidgetRepresentation(view, 'LineWidgetRepresentation')
            setattr(proxy.__class__, 'UpdateWidget', _line_update_widget)
            setattr(proxy.__class__, 'WidgetUpdate', _line_widget_update)
            proxy.UpdateWidget(widgetProxy)
            proxy.Observed = widgetProxy
            proxy.ObserverTag = widgetProxy.AddObserver("EndInteractionEvent", proxy.WidgetUpdate)
        elif proxy.__class__.__name__ in ['Distance', 'Ruler'] :
            widgetProxy = self.CreateWidgetRepresentation(view, 'DistanceWidgetRepresentation')
            setattr(proxy.__class__, 'UpdateWidget', _line_update_widget)
            setattr(proxy.__class__, 'WidgetUpdate', _line_widget_update)
            proxy.UpdateWidget(widgetProxy)
            proxy.Observed = widgetProxy
            proxy.ObserverTag = widgetProxy.AddObserver("EndInteractionEvent", proxy.WidgetUpdate)
        elif proxy.__class__.__name__ == 'Sphere':
            widgetProxy = self.CreateWidgetRepresentation(view, 'SphereWidgetRepresentation')
        elif proxy.__class__.__name__ == 'Spline':
            widgetProxy = self.CreateWidgetRepresentation(view, 'SplineWidgetRepresentation')
        else:
            print "No widget representation for %s" % proxy.__class__.__name__

        return widgetProxy.GetGlobalIDAsString()

    def CreateWidgetRepresentation(self, view, name):
        proxy = simple.servermanager.CreateProxy("representations", name, None)
        pythonWrap = simple.servermanager.rendering.__dict__[proxy.GetXMLName()]()
        pythonWrap.UpdateVTKObjects()
        view.Representations.append(pythonWrap)
        pythonWrap.Visibility = 1
        pythonWrap.Enabled = 1
        return pythonWrap
