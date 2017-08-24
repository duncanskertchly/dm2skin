import numpy as np
from os.path import splitext
from os.path import basename
from scipy.optimize import minimize
import maya.cmds as cmds
import maya.mel as mel
import math

from Qt import QtCore, QtWidgets
from maya import OpenMayaUI as omui

if int(cmds.about(v = True)) < 2017:
    from shiboken import wrapInstance
else:
    from shiboken2 import wrapInstance


mayaMainWindowPtr = omui.MQtUtil.mainWindow()
mayaMainWindow = wrapInstance(long(mayaMainWindowPtr), QtWidgets.QWidget)


class dm2skin_UI(QtWidgets.QDialog):
    """Builds the GUI"""

    def __init__(self, parent=mayaMainWindow):
        super(dm2skin_UI, self).__init__(parent)

        self.setWindowTitle('dm2skin')

        self.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.setFixedHeight(175)

        self.setLayout(QtWidgets.QVBoxLayout())
        self.layout().setAlignment(QtCore.Qt.AlignTop)

        self.setLayout(QtWidgets.QVBoxLayout())
        self.layout().setContentsMargins(7, 7, 7, 7)
        self.layout().setSpacing(5)

        self.sourceLayout = QtWidgets.QVBoxLayout()
        self.layout().addLayout(self.sourceLayout)

        self.sourceFieldLayout = QtWidgets.QHBoxLayout()
        self.sourceLayout.addLayout(self.sourceFieldLayout)

        self.sourceText = QtWidgets.QLabel('Source Mesh:')
        self.sourceField = QtWidgets.QLineEdit()
        self.loadSourceButton = QtWidgets.QPushButton('<<')
        self.loadSourceButton.clicked.connect(self.setSourceMesh)
        self.createMushButton = QtWidgets.QPushButton('Create Mush')
        self.createMushButton.clicked.connect(self.createMush)

        self.sourceFieldLayout.addWidget(self.sourceText)
        self.sourceFieldLayout.addWidget(self.sourceField)
        self.sourceFieldLayout.addWidget(self.loadSourceButton)

        self.sourceLayout.addWidget(self.createMushButton)

        self.displayLayout = QtWidgets.QHBoxLayout()
        self.toggleMeshButton = QtWidgets.QPushButton('Toggle Mesh Visibility')
        self.toggleMushButton = QtWidgets.QPushButton('Toggle Mush Visibility')
        self.toggleMeshButton.clicked.connect(self.toggleMeshVisibility)
        self.toggleMushButton.clicked.connect(self.toggleMushVisbility)
        self.displayLayout.addWidget(self.toggleMeshButton)
        self.displayLayout.addWidget(self.toggleMushButton)

        self.layout().addLayout(self.displayLayout)

        self.infsLayout = QtWidgets.QHBoxLayout()
        self.maxInfsLabel = QtWidgets.QLabel('Max Influences:')
        self.maxInfsLabel.setFixedWidth(83)
        self.maxInfsSpinBox = QtWidgets.QSpinBox()
        self.maxInfsSpinBox.setFixedWidth(50)
        self.maxInfsSpinBox.setMinimum(2)
        self.maxInfsSpinBox.setValue(4)
        self.transferButton = QtWidgets.QPushButton('Transfer To Skin')

        self.infsLayout.addWidget(self.maxInfsLabel)
        self.infsLayout.addWidget(self.maxInfsSpinBox)
        self.infsLayout.addWidget(self.transferButton)
        self.layout().addLayout(self.infsLayout)

        self.transferButton.clicked.connect(self.startWeightTransfer)

        self.transferLayout = QtWidgets.QVBoxLayout()
        self.deleteMushButton = QtWidgets.QPushButton('Delete Mush')
        self.deleteMushButton.clicked.connect(self.deleteMush)

        self.progressBar = QtWidgets.QProgressBar()

        self.layout().addLayout(self.transferLayout)
        self.transferLayout.addWidget(self.deleteMushButton)
        self.transferLayout.addWidget(self.progressBar)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

    def toggleMeshVisibility(self):
        mesh = self.sourceField.text()
        if not mesh:
            return
        if not cmds.objExists(mesh):
            return
        try:
            cmds.setAttr(mesh + '.visibility', not bool(cmds.getAttr(mesh + '.visibility')))
        except Exception as e:
            print(e)

    def toggleMushVisbility(self):
        mush = self.sourceField.text()
        if not mush:
            return
        mush += '_Mush'
        if not cmds.objExists(mush):
            return
        try:
            cmds.setAttr(mush + '.visibility', not bool(cmds.getAttr(mush + '.visibility')))
        except Exception as e:
            print(e)

    def setSourceMesh(self):
        sel = cmds.ls(sl=True, type='transform')
        if not sel:
            return
        childMeshes = cmds.listRelatives(sel[0], c=True, type='mesh')
        if not childMeshes:
            return
        self.sourceField.setText(sel[0])

        maxInfs = dm2skin_getMaxInfluences(sel[0])
        self.maxInfsSpinBox.setMaximum(maxInfs)
        return True

    def createMush(self):
        mesh = self.sourceField.text()
        if not mesh:
            return
        if cmds.objExists(mesh + '_Mush'):
            print(mesh + '_Mush already exists!')
            return
        cmds.currentTime(cmds.playbackOptions(q=True, min=True))
        dup = cmds.duplicate(mesh, inputConnections=True, n=mesh + '_Mush')
        cmds.deltaMush(dup, smoothingIterations=20, smoothingStep=0.5, pinBorderVertices=True, envelope=1)

    def deleteMush(self):
        mesh = self.sourceField.text()
        if not mesh:
            return
        if not cmds.objExists(mesh + '_Mush'):
            return
        cmds.delete(mesh + '_Mush')

    def startWeightTransfer(self):
        mesh = self.sourceField.text()
        if not mesh:
            return
        if not (cmds.objExists(mesh) or cmds.objExists(mesh + '_Mush')):
            print('Missing mesh or mush!')
            return
        dm2skin_doMushOptimization(mesh, mushMesh=mesh + '_Mush', maxInfluences=int(self.maxInfsSpinBox.value()), progressBar=self.progressBar)


def dm2skin_getMatrices(joints, matrixString=".worldMatrix"):
    """Returns a list of numpy arrays representing the transform
    matrices of the given list of joints."""
    retMatrices = []
    for j in joints:
        tempMatrix = cmds.getAttr(j + matrixString)
        trfMatrix = np.array([      [tempMatrix[0], tempMatrix[1], tempMatrix[2], tempMatrix[3]],
                                    [tempMatrix[4], tempMatrix[5], tempMatrix[6], tempMatrix[7]],
                                    [tempMatrix[8], tempMatrix[9], tempMatrix[10], tempMatrix[11]],
                                    [tempMatrix[12], tempMatrix[13], tempMatrix[14], tempMatrix[15]]
                            ])
        retMatrices.append(trfMatrix)
    return retMatrices


def dm2skin_getMatricesOverRange(joints, matrixString='.worldMatrix', startFrame=0, endFrame=1):
    """Gets a list of lists of transform matrices for the given joints. One
    list for each frame between startFrame and endFrame."""
    resultList = []
    for i in range(startFrame, endFrame + 1):
        cmds.currentTime(i)
        resultList.append(dm2skin_getMatrices(joints, matrixString=matrixString))
    return resultList


def dm2skin_getVertexPositionsOverRange(mesh, startFrame=0, endFrame=1):
    """Gets a list of lists of vertex positions for the given mesh. One list for
    each frame between startFrame and endFrame."""
    numVerts = cmds.polyEvaluate(mesh, v=True)
    resultList = []
    for i in range(startFrame, endFrame + 1):
        tempList = []
        cmds.currentTime(i)
        for j in range(0, numVerts):
            tempPos = cmds.xform(mesh + '.vtx[' + str(j) + ']', q=True, ws=True, t=True)
            tempList.append(np.array([tempPos[0], tempPos[1], tempPos[2]]))
        resultList.append(tempList)
    return resultList


def dm2skin_getVertexLocationList(mesh, frame=0):
    """Gets a list of vertex locations on the given frame."""
    numVerts = cmds.polyEvaluate(mesh, v=True)
    resultList = []
    cmds.currentTime(frame)
    for v in range(0, numVerts):
        pos = cmds.xform(mesh + '.vtx[' + str(v) + ']', q=True, ws=True, t=True)
        resultList.append(np.array([pos[0], pos[1], pos[2], 1.0]))
    return resultList


def dm2skin_getLargestInfluenceOnVert(vertex, skinCluster=None):
    """Given a vertex returns the largest influence in the provided
    skin cluster that acts upon it."""
    if not skinCluster:
        return False

    vertInfs = cmds.skinCluster(skinCluster, q=True, inf=True)
    vertVals = cmds.skinPercent(skinCluster, vertex, q=True, value=True)
    return vertInfs[vertVals.index(max(vertVals))]


def dm2skin_getNeighbouringJoints(joint, vertexString=None, cluster=None, influences=3):
    """This gets a list of nearby joints in the skin cluster to joint up to
    the number of influences. These will be the ones we use in our minimization
    later"""

    if not cmds.objExists(joint):
        return False
    if influences < 3:
        return False
    if not cluster:
        return False

    clusterJoints = cmds.skinCluster(cluster, q=True, inf=True)

    pos1 = cmds.xform(vertexString, q=True, ws=True, t=True)

    parentJoint = cmds.listRelatives(joint, parent=True)

    subtract = 1
    # add the main joint
    resultList = [joint]
    # i've found it works best to always include the parent
    if parentJoint and parentJoint in clusterJoints:
        resultList.insert(0, parentJoint[0])
        subtract = 2

    # for the rest of the available influences get a list of nearby joints in space
    measureList = []
    for measureJnt in clusterJoints:
        if measureJnt not in resultList:
            jntPos2 = cmds.xform(measureJnt, q=True, ws=True, t=True)
            #this just gets the length of the vector between the two joints
            dist = math.sqrt(reduce(lambda x, y: x + y, [math.pow(jntPos2[i] - pos1[i], 2) for i in range(len(pos1))]))
            measureList.append((measureJnt, dist))

    # sort the list in ascending order so we get the closest joints first
    measureList.sort(key=lambda dist: dist[1])
    ascendingList = [entry[0] for entry in measureList[0:influences - subtract]]
    return resultList + ascendingList


def dm2skin_computeSourceMushDistance(weights, sourceMesh, targetMesh, index, bindVerts, mushVerts, bindInvMatrices, transMatrices, joints):
    """Computes the distance between a vertex in the source mesh and target mesh. Ultimately this
    distance is what we use scipy to minimize."""
    totalDist = 0
    vert = index
    for frame in range(len(mushVerts)):
        bindVertPos = bindVerts[vert]
        mushedPos = mushVerts[frame][vert]
        transformedPos = dm2skin_transformPoint(bindVertPos, joints=joints, weights=weights, inverseMatrices=bindInvMatrices, transformMatrices=transMatrices[frame])
        totalDist += np.linalg.norm(transformedPos - mushedPos)
    return totalDist


def dm2skin_transformPoint(bindPosition, joints=[], weights=[], inverseMatrices=[], transformMatrices=[]):
    """Given the bind pose position of a vertex computes the eventual position of the
    vertex once it has had the standard linear skinning algorithm applied"""
    finalPos = np.array(np.zeros(4))
    for i in range(len(joints)):
        inversePos = np.dot(bindPosition, inverseMatrices[i])
        finalPos += weights[i] * np.dot(inversePos, transformMatrices[i])
    return finalPos[:3]


def dm2skin_normalizeWeightsConstraint(x):
    """Constraint used in optimization that ensures
    the weights in the solution sum to 1"""
    return sum(x) - 1.0


def dm2skin_getMaxInfluences(mesh):
    """Finds a skin cluster on the given mesh and returns
    the number of influences it is set to have."""
    skinClusterStr = 'findRelatedSkinCluster("' + mesh + '")'
    skinCluster = mel.eval(skinClusterStr)
    if not skinCluster:
        return 0
    allInfluences = cmds.skinCluster(skinCluster, q=True, inf=True)
    return len(allInfluences)


def dm2skin_getNumberOfNonZeroElements(list):
    """Returns the number of non-zero elements in the given list"""
    return int(sum([1 for x in list if x != 0.0]))


def dm2skin_doMushOptimization(mesh, mushMesh=None, maxInfluences=4, progressBar=None):
    """Does the actual job of solving the minimization problem."""

    if not mushMesh:
        return False

    minTime = cmds.playbackOptions(q=True, min=True)
    maxTime = cmds.playbackOptions(q=True, max=True)
    # assume the first frame is the bind pose
    cmds.currentTime(minTime)

    skinClusterStr = 'findRelatedSkinCluster("' + mesh + '")'
    skinCluster = mel.eval(skinClusterStr)
    if not skinCluster:
        return False

    allInfluences = cmds.skinCluster(skinCluster, q=True, inf=True)
    numVerts = cmds.polyEvaluate(mesh, v=True)

    invMatrices = dm2skin_getMatrices(allInfluences, matrixString='.worldInverseMatrix')
    transMatrices = dm2skin_getMatricesOverRange(allInfluences, matrixString='.worldMatrix', startFrame=int(minTime) + 1, endFrame=int(maxTime))

    bindVertList = dm2skin_getVertexLocationList(mesh, frame=int(minTime))
    mushedVertList = dm2skin_getVertexPositionsOverRange(mushMesh, startFrame=int(minTime) + 1, endFrame=int(maxTime))

    # if there is a progress bar provided, set the maximum value to
    # the total number of verts
    if progressBar:
        progressBar.setMaximum(numVerts)

    setWeightList = []

    # reset to the first frame again before we start
    cmds.currentTime(minTime)
    for i in range(numVerts):

        if progressBar:
            progressBar.setValue(i)

        largestInf = dm2skin_getLargestInfluenceOnVert(mesh + '.vtx[' + str(i) + ']', skinCluster)
        vertInfluences = dm2skin_getNeighbouringJoints(largestInf, vertexString=mesh +'.vtx[' +str(i) +']', cluster=skinCluster, influences=maxInfluences)

        if not vertInfluences:
            print("Error getting neighbour joints")
            progressBar.setValue(0)
            return

        properInfIndices = [allInfluences.index(inf) for inf in vertInfluences]

        currentInvMatrices = []
        currentTransMatrices = []

        currentInvMatrices = [invMatrices[pi] for pi in properInfIndices]

        for t in range(len(transMatrices)):
            currentTransMatrices.append([transMatrices[t][ind] for ind in properInfIndices])

        boundsList = []
        startValList = []
        for j in range(len(vertInfluences)):
            boundsList.append((0, 1))
            startValList.append(1.0 / len(vertInfluences))

        cons = ({'type': 'eq', 'fun': dm2skin_normalizeWeightsConstraint})
        result = minimize(dm2skin_computeSourceMushDistance, startValList, method='SLSQP', args=(mushMesh, mesh, i, bindVertList, mushedVertList, currentInvMatrices, currentTransMatrices, vertInfluences), constraints=cons, bounds=boundsList)
        tempList = []
        for j in range(len(vertInfluences)):
            tempList.append((vertInfluences[j], np.around(result.x[j], 3)))
        setWeightList.append(tempList)

    # open an undo chunk
    cmds.undoInfo(openChunk=True)

    # lock the allInfluences, then we can change the max influences on
    # the skin cluster
    for inf in allInfluences:
        cmds.skinCluster(skinCluster, e=True, inf=inf, lw=True)

    # the scipy solve might not neccesarily have used all the
    # available influences, so this block checks through each
    # set of weights and finds the highest number of non zero
    # ones
    maxInfsUsed = 0
    for i in range(numVerts):
        vertInfVals = [setWeightList[i][j][1] for j in range(len(setWeightList[i]))]
        numNonZero = dm2skin_getNumberOfNonZeroElements(vertInfVals)
        if numNonZero > maxInfsUsed:
            maxInfsUsed = numNonZero

    # set the new number of influences on the skin cluster and
    # unlock the influences
    cmds.skinCluster(skinCluster, e=True, mi=maxInfsUsed)
    for inf in allInfluences:
        cmds.skinCluster(skinCluster, e=True, inf=inf, lw=False)

    # set the new weights
    for i in range(numVerts):
        cmds.skinPercent(skinCluster, mesh +'.vtx[' + str(i) + ']', normalize=True, relative=False, zri=True, transformValue=setWeightList[i])

    # close undo chunk and reset progress bar
    cmds.undoInfo(closeChunk=True)

    if progressBar:
        progressBar.setValue(0)


def deleteInstances():
    fileName = splitext(basename(__file__))[0]
    for obj in mayaMainWindow.children():
        if(str(type(obj)) == "<class '{0}.dm2skin_UI'>".format(fileName)):
            if(obj.__class__.__name__ == "dm2skin_UI"):
                obj.setParent(None)
                obj.deleteLater()


def dm2skin():
    deleteInstances()
    ui = dm2skin_UI()
    ui.show()
