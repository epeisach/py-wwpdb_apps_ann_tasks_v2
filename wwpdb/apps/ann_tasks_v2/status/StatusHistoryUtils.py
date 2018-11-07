##
# File:  StatusHistoryUtils.py
# Date:  15-Jan-2015  J. Westbrook
#
# Updated:
#
# 29-Jan-2015  jdw   add special support for AUTH|WAIT
# 30-Jan-2015  jdw   add special case for REPL|AUCO
#  7-Aug-2015  jdw   fix number of returned argument for getCurrentStatusDetail()
#
"""
Wrapper for utilities for database loading of status history data content from
repository directories.

"""
__docformat__ = "restructuredtext en"
__author__ = "John Westbrook"
__email__ = "jwest@rcsb.rutgers.edu"
__license__ = "Creative Commons Attribution 3.0 Unported"
__version__ = "V0.07"

import sys
import os
import os.path
import time
import copy
import scandir
import traceback
from itertools import izip_longest

from wwpdb.apps.ann_tasks_v2.status.StatusHistory import StatusHistory
from wwpdb.utils.config.ConfigInfo import ConfigInfo
from wwpdb.utils.db.MyDbSqlGen import MyDbAdminSqlGen
from wwpdb.utils.db.SchemaDefLoader import SchemaDefLoader
from wwpdb.utils.db.MyDbUtil import MyDbConnect, MyDbQuery

from rcsb.utils.multiproc.MultiProcUtil import MultiProcUtil

from wwpdb.utils.db.StatusHistorySchemaDef import StatusHistorySchemaDef
from mmcif.io.IoAdapterCore import IoAdapterCore
from pdbx_v2.pdbx.PdbxIo import PdbxEntryInfoIo
from wwpdb.io.locator.PathInfo import PathInfo
from wwpdb.utils.rcsb.DataFile import DataFile


from wwpdb.utils.db.MyConnectionBase import MyConnectionBase


class StatusHistoryUtils(MyConnectionBase):

    """ Wrapper for utilities for database loading of content from PRD repositories and sandboxes.
    """
    #

    def __init__(self, reqObj, verbose=True, log=sys.stderr):
        super(StatusHistoryUtils, self).__init__(verbose=verbose, log=log)
        """
        """
        self.__verbose = verbose
        self.__lfh = log
        self.__debug = False
        #
        # Information injected from the request object -
        #
        self.__reqObj = reqObj
        self.__topPath = self.__reqObj.getValue("TopPath")
        self.__topSessionPath = self.__reqObj.getValue("TopSessionPath")
        #
        self.__sObj = self.__reqObj.getSessionObj()
        self.__sessionPath = self.__sObj.getPath()
        self.__sessionRelativePath = self.__sObj.getRelativePath()
        self.__sessionId = self.__sObj.getId()
        #
        self.__ioObj = IoAdapterCore(verbose=self.__verbose, log=self.__lfh)
        #
        self.__siteId = self.__reqObj.getValue("WWPDB_SITE_ID")
        self.__cI = ConfigInfo(self.__siteId)
        self.__fileSource = 'archive'
        self.__archPath = os.path.join(self.__cI.get('SITE_ARCHIVE_STORAGE_PATH'), 'archive')
        self.__pI = PathInfo(siteId=self.__siteId, verbose=self.__verbose, log=self.__lfh)

    def getEntryIdList(self):
        dList, pList = self.__makeEntryPathList(self.__archPath)
        rL = list(set(dList))
        return rL

    def getStatusHistoryPathList(self):
        if self.__verbose:
            self.__lfh.write("+StatusHistoryUtils.getStatusHistoryPathList() search archive path  %r\n" % self.__archPath)
        hList = []
        tList, pList = self.__makeEntryPathList(self.__archPath)
        dList = list(set(tList))
        for d in dList:
            tPath = self.__pI.getStatusHistoryFilePath(dataSetId=d, fileSource=self.__fileSource, versionId="latest")
            if os.access(tPath, os.R_OK):
                hList.append(tPath)
        if self.__debug:
            self.__lfh.write("+StatusHistoryUtils.getStatusHistoryPathList() pathlist is %r\n" % hList)
        return hList

    def getEntryStatusHistoryPathList(self, entryIdList):
        hList = []
        for d in entryIdList:
            tPath = self.__pI.getStatusHistoryFilePath(dataSetId=d, fileSource=self.__fileSource, versionId="latest")
            if os.access(tPath, os.R_OK):
                hList.append(tPath)
        if self.__debug:
            self.__lfh.write("+StatusHistoryUtils.getEntryStatusHistoryPathList() pathlist is %r\n" % hList)
        return hList

    def __makeEntryPathList(self, archivePath):
        """ Return the list of entries in the archive directory names and paths -
        """
        pathList = []
        dataList = []
        for root, dirs, files in scandir.walk(archivePath, topdown=False):
            for dir in dirs:
                if dir.startswith("D_") and len(dir) == 12:
                    pathList.append(os.path.join(root, dir))
                    dataList.append(dir)
        return dataList, pathList

#
    def createHistory(self, entryIdList, overWrite=False, statusUpdateAuthWait=None):
        """ Read existing entry and create initial status records as required
        """
        startTime = time.time()
        self.__lfh.write("\n\n========================================================================================================\n")
        self.__lfh.write("Starting %s %s at %s\n" % (self.__class__.__name__,
                                                     sys._getframe().f_code.co_name,
                                                     time.strftime("%Y %m %d %H:%M:%S", time.localtime())))
        rList = []
        for entryId in entryIdList:
            ok = self.__createStatusHistoryFile(entryId, overWrite=overWrite, statusUpdateAuthWait=statusUpdateAuthWait)
            if ok:
                rList.append(entryId)
        #
        endTime = time.time()
        self.__lfh.write("\nCompleted %s %s at %s (%.2f seconds)\n" % (self.__class__.__name__,
                                                                       sys._getframe().f_code.co_name,
                                                                       time.strftime("%Y %m %d %H:%M:%S", time.localtime()),
                                                                       endTime - startTime))
        return rList

    def createHistoryMulti(self, entryIdList, numProc=2, overWrite=False):
        startTime = time.time()
        self.__lfh.write("\n\n========================================================================================================\n")
        self.__lfh.write("Starting %s %s at %s\n" % (self.__class__.__name__,
                                                     sys._getframe().f_code.co_name,
                                                     time.strftime("%Y %m %d %H:%M:%S", time.localtime())))
        oD = {}
        oD['overWrite'] = overWrite
        mpu = MultiProcUtil(verbose=True, log=self.__lfh)
        mpu.set(workerObj=self, workerMethod="createHistoryWorker")
        mpu.setOptions(optionsD=oD)
        mpu.setWorkingDir(self.__sessionPath)
        ok, failList, retLists, diagList = mpu.runMulti(dataList=entryIdList, numProc=numProc, numResults=1)
        #
        endTime = time.time()
        self.__lfh.write("\nCompleted %s %s at %s (%.2f seconds)\n" % (self.__class__.__name__,
                                                                       sys._getframe().f_code.co_name,
                                                                       time.strftime("%Y %m %d %H:%M:%S", time.localtime()),
                                                                       endTime - startTime))
        return retLists[0]
        #

    def createHistoryWorker(self, dataList, procName, optionsD, workingDir):
        if 'overWrite' in optionsD:
            overWrite = optionsD['overWrite']
        else:
            overWrite = False
        rList = []
        for entryId in dataList:
            ok = self.__createStatusHistoryFile(entryId=entryId, overWrite=overWrite, statusUpdateAuthWait=None)
            if ok:
                rList.append(entryId)
        #
        return rList, rList, []

    def __getModelFileTimeStamp(self, entryId, versionId="1", mileStone=None, defValue=None):
        try:
            # Get the modification date for the model file with mileStone
            modelFilePath = self.__pI.getModelPdbxFilePath(entryId, wfInstanceId=None, fileSource=self.__fileSource, versionId=versionId, mileStone=mileStone)
            if self.__debug:
                self.__lfh.write("+StatusHistoryUtils.__getModelFileTimeStamp()) %s checking for model milestone=%r path %s\n" % (entryId, mileStone, modelFilePath))
            df = DataFile(fPath=modelFilePath)
            if (df.srcFileExists()):
                retDate = df.srcModTimeStamp()
                if self.__verbose:
                    self.__lfh.write("+StatusHistoryUtils.__getModelFileTimeStamp() %s model file milestone %s timestamp %r\n" % (entryId, mileStone, retDate))
                return retDate
        except:
            traceback.print_exc(file=self.__lfh)

        return defValue

    def __createStatusHistoryFile(self, entryId, overWrite=False, statusUpdateAuthWait=None):
        """ Read existing entry and create initial status records as required

            overWrite = controls if existing files are rewritten.
            statusUpdateAuthWait = [AUTH,WAIT]
                                    This special case is required to create initial status
                                    from the status module at the on the first setting of AUTH/WAIT status.
        """
        statusFlag = False
        try:
            # Read model file and return status dictionary -
            if self.__verbose:
                self.__lfh.write("\n%s\n" % ('-' * 50))
                self.__lfh.write("\n+StatusHistoryUtils.createHistory() %s begin create initial status history file\n" % entryId)

            currentModelTimeStamp = self.__getModelFileTimeStamp(entryId, versionId="latest", mileStone=None, defValue=None)
            if currentModelTimeStamp is None:
                if self.__verbose:
                    self.__lfh.write("+StatusHistoryUtils.createHistory() %s no model file in file source %s\n" % (entryId, self.__fileSource))
                return statusFlag
            if self.__verbose:
                self.__lfh.write("+StatusHistoryUtils.createHistory() %s model file modification time %r\n" % (entryId, currentModelTimeStamp))
            #
            filePath = self.__pI.getModelPdbxFilePath(entryId, wfInstanceId=None, fileSource=self.__fileSource, versionId="latest", mileStone=None)
            ei = PdbxEntryInfoIo(verbose=self.__verbose, log=self.__lfh)
            ei.setFilePath(filePath=filePath, idCode=entryId)
            # sD = ei.getInfoD(contextType="history")
            tId, pdbId, statusCode, authReleaseCode, annotatorInitials, initialDepositionDate, beginProcessingDate, authorApprovalDate, \
                releaseDate = ei.getCurrentStatusDetails()
            #
            if self.__verbose:
                self.__lfh.write("+StatusHistoryUtils.createHistory() %s begin proccessing date time %r\n" % (entryId, beginProcessingDate))

            # Get the modification date for the model file  milestone = annotate-
            endFirstStepDate = self.__getModelFileTimeStamp(entryId, versionId="1", mileStone='annotate', defValue=currentModelTimeStamp)
            if self.__verbose:
                self.__lfh.write("+StatusHistoryUtils.createHistory() %s model file (annotate) timestamp used for auth step date %r\n" % (entryId, endFirstStepDate))

            #
            sH = StatusHistory(siteId=self.__siteId, fileSource='archive', sessionPath=self.__sessionPath, verbose=self.__verbose, log=self.__lfh)
            if not sH.dateTimeOk(initialDepositionDate):
                if self.__verbose:
                    self.__lfh.write("+StatusHistoryUtils.createHistory() %s model file missing initial deposition date\n" % entryId)
                return statusFlag

            if not sH.dateTimeOk(beginProcessingDate) and not sH.dateTimeOk(endFirstStepDate):
                if self.__verbose:
                    self.__lfh.write("+StatusHistoryUtils.createHistory() %s model file missing beginning processing date\n" % entryId)
                return statusFlag

            if not sH.dateTimeOk(beginProcessingDate) and sH.dateTimeOk(endFirstStepDate):
                beginProcessingDate = endFirstStepDate

            if not sH.dateTimeOk(endFirstStepDate) and sH.dateTimeOk(beginProcessingDate):
                endFirstStepDate = beginProcessingDate

            numHist = sH.setEntryId(entryId=entryId, pdbId=pdbId, overWrite=overWrite)
            #
            if ((statusUpdateAuthWait is not None) and (numHist < 1) and (statusCode in ['PROC'])):
                statusCode = statusUpdateAuthWait
                endFirstStepDate = sH.getNow()

            #
            success = False
            if ((numHist < 1) and (statusCode not in ['PROC', 'WAIT'])):
                # New status history?  The first three records of a new file will mark the
                #  PROC->PROC_ST_1, PROC_ST_1->AUTH, and the overall PROC->AUTH transitions.
                #
                sH.add(statusCodeBegin='PROC', dateBegin=initialDepositionDate,
                       statusCodeEnd='PROC_ST_1', dateEnd=beginProcessingDate,
                       annotator=annotatorInitials, details="Automated initial entry")

                sH.add(statusCodeBegin='PROC_ST_1', dateBegin=beginProcessingDate,
                       statusCodeEnd='AUTH', dateEnd=endFirstStepDate,
                       annotator=annotatorInitials, details="Automated initial entry")

                sH.add(statusCodeBegin='PROC', dateBegin=initialDepositionDate,
                       statusCodeEnd='AUTH', dateEnd=endFirstStepDate,
                       annotator=annotatorInitials, details="Automated initial entry")

                if statusCode in ['REL']:
                    sH.add(statusCodeBegin='AUTH', dateBegin=endFirstStepDate,
                           statusCodeEnd=statusCode, dateEnd=releaseDate,
                           annotator=annotatorInitials, details="Automated initial entry")

                elif statusCode in ['HOLD', 'HPUB']:
                    sH.add(statusCodeBegin='AUTH', dateBegin=endFirstStepDate,
                           statusCodeEnd=statusCode, dateEnd=authorApprovalDate,
                           annotator=annotatorInitials, details="Automated initial entry")

                elif statusCode in ['AUCO', 'REPL']:
                    # Get the modification date for the latest model file  milestone = deposit -
                    revStepDate = self.__getModelFileTimeStamp(entryId, versionId="latest", mileStone='deposit', defValue=currentModelTimeStamp)
                    if self.__verbose:
                        self.__lfh.write("+StatusHistoryUtils.createHistory() %s model file (deposit) timestamp used for revision step date %r\n" % (entryId, revStepDate))
                    sH.add(statusCodeBegin='AUTH', dateBegin=endFirstStepDate,
                           statusCodeEnd=statusCode, dateEnd=revStepDate,
                           annotator=annotatorInitials, details="Automated initial entry")
                success = True
                #
            elif ((numHist < 1) and (statusCode in ['WAIT'])):
                # New status history?  The first three records of a new file will mark the
                #  PROC->PROC_ST_1, PROC_ST_1->WAIT, and the overall PROC->WAIT transitions.
                #
                sH.add(statusCodeBegin='PROC', dateBegin=initialDepositionDate,
                       statusCodeEnd='PROC_ST_1', dateEnd=beginProcessingDate,
                       annotator=annotatorInitials, details="Automated initial entry")

                sH.add(statusCodeBegin='PROC_ST_1', dateBegin=beginProcessingDate,
                       statusCodeEnd='WAIT', dateEnd=endFirstStepDate,
                       annotator=annotatorInitials, details="Automated initial entry")

                sH.add(statusCodeBegin='PROC', dateBegin=initialDepositionDate,
                       statusCodeEnd='WAIT', dateEnd=endFirstStepDate,
                       annotator=annotatorInitials, details="Automated initial entry")
                success = True

            if success:
                (lastStatus, lastDate) = sH.getLastStatusAndDate()
                if self.__debug:
                    self.__lfh.write("+StatusHistoryUtils.createHistory() %s last status history and timestamp %r %r\n" % (entryId, lastStatus, lastDate))
                #
                #  Save the current status history file --
                ok = sH.store(entryId=entryId)
                if ok:
                    statusFlag = True
                if self.__verbose:
                    if ok:
                        self.__lfh.write("+StatusHistoryUtils.createHistory() %s write status history succeeded\n" % entryId)
                    else:
                        self.__lfh.write("+StatusHistoryUtils.createHistory() %s NO status history file written\n" % entryId)
                #
            else:
                if self.__verbose:
                    if (numHist > 0):
                        self.__lfh.write("+StatusHistoryUtils.createHistory() %s found existing status history category with row count %r\n" % (entryId, numHist))
                    self.__lfh.write("+StatusHistoryUtils.createHistory() %s skipping entry with current status code is %r\n" % (entryId, statusCode))
            #
            #
            # Recover the contents of the current history file -
            #
            if (self.__debug):
                sH = StatusHistory(siteId=self.__siteId, fileSource=self.__fileSource, sessionPath=self.__sessionPath, verbose=self.__verbose, log=self.__lfh)
                nRows = sH.setEntryId(entryId=entryId, pdbId=pdbId)
                self.__lfh.write("+StatusHistoryUtils.createHistory() %s recovered history records %d\n" % (entryId, nRows))
                dList = sH.get()
                for ii, d in enumerate(dList):
                    self.__lfh.write("+StatusHistoryUtils.createHistory() %s history record %r  : %r\n" % (entryId, ii, d.items()))

        except:
            statusFlag = False
            traceback.print_exc(file=self.__lfh)

        return statusFlag

    def __schemaCreate(self, schemaDefObj):
        """Create and load table schema using schema definition
        """
        startTime = time.time()
        self.__lfh.write("\n+StatusHistoryUtils(__schemaCreate) Starting %s %s at %s\n" % (self.__class__.__name__,
                                                                                           sys._getframe().f_code.co_name,
                                                                                           time.strftime("%Y %m %d %H:%M:%S", time.localtime())))
        try:
            tableIdList = schemaDefObj.getTableIdList()
            sqlGen = MyDbAdminSqlGen(self.__verbose, self.__lfh)
            sqlL = []
            for tableId in tableIdList:
                tableDefObj = schemaDefObj.getTable(tableId)
                sqlL.extend(sqlGen.createTableSQL(databaseName=schemaDefObj.getDatabaseName(), tableDefObj=tableDefObj))

            if (self.__debug):
                self.__lfh.write("\n+StatusHistoryUtils(__schemaCreate) Schema creation SQL string\n %s\n\n" % '\n'.join(sqlL))

            myQ = MyDbQuery(dbcon=self._dbCon, verbose=self.__verbose, log=self.__lfh)
            #
            # Permit warnings to support "drop table if exists" for missing tables.
            #
            myQ.setWarning('default')
            ret = myQ.sqlCommand(sqlCommandList=sqlL)
            if (self.__verbose):
                self.__lfh.write("\n\n+INFO mysql server returns %r\n" % ret)
        except:
            traceback.print_exc(file=self.__lfh)
            return False

        endTime = time.time()
        self.__lfh.write("\n+StatusHistoryUtils(__schemaCreate) Completed %s %s at %s (%.2f seconds)\n" % (self.__class__.__name__,
                                                                                                           sys._getframe().f_code.co_name,
                                                                                                           time.strftime("%Y %m %d %H:%M:%S", time.localtime()),
                                                                                                           endTime - startTime))
        return ret

    def __makeSubLists(self, n, iterable):
        args = [iter(iterable)] * n
        return ([e for e in t if e is not None] for t in izip_longest(*args))

    def loadBatchFilesWorker(self, dataList, procName, optionsD, workingDir):
        """ Load tabular batch files created for the chemical component definitions into the database server.
        """
        shsd = StatusHistorySchemaDef()
        myC = MyDbConnect(verbose=self.__verbose, log=self.__lfh)
        myC.setAuth(optionsD)
        dbCon = myC.connect()
        sdl = SchemaDefLoader(schemaDefObj=shsd, ioObj=self.__ioObj, dbCon=dbCon, workPath=workingDir, cleanUp=False,
                              warnings='default', verbose=self.__verbose, log=self.__lfh)
        #
        sdl.loadBatchFiles(loadList=dataList, containerNameList=None, deleteOpt=None)

        myC.close()
        return dataList, dataList, []

    def loadStatusHistoryMulti(self, numProc=2, newTable=False):
        """ Create batch load files for all status history data files - (multiprocessing version)
        """
        if self.__verbose:
            self.__lfh.write("\nStarting %s %s\n" % (self.__class__.__name__, sys._getframe().f_code.co_name))
        startTime = time.time()
        try:
            pathList = self.getStatusHistoryPathList()
            if self.__verbose:
                self.__lfh.write("\n+StatusHistoryUtils(loadStatusHistoryMulti) numProc %d session %s pathList length %d \n" %
                                 (numProc, self.__sessionPath, len(pathList)))
            if len(pathList) < 1:
                return True

            shsd = StatusHistorySchemaDef()
            sml = SchemaDefLoader(schemaDefObj=shsd, ioObj=self.__ioObj, dbCon=None, workPath=self.__sessionPath, cleanUp=False,
                                  warnings='default', verbose=self.__verbose, log=self.__lfh)

            #
            mpu = MultiProcUtil(verbose=True, log=self.__lfh)
            mpu.set(workerObj=sml, workerMethod="makeLoadFilesMulti")
            mpu.setWorkingDir(self.__sessionPath)
            ok, failList, retLists, diagList = mpu.runMulti(dataList=pathList, numProc=numProc, numResults=2)
            #
            containerNameList = retLists[0]
            tList = retLists[1]

            if self.__verbose:
                for tId, fn in tList:
                    self.__lfh.write("\nCreated table %s load file %s\n" % (tId, fn))
            #
            endTime1 = time.time()
            if self.__verbose:
                self.__lfh.write("\nBatch files created in %.2f seconds\n" % (endTime1 - startTime))

            self.setResource(resourceName="DA_INTERNAL")
            ok = self.openConnection()
            #
            authD = copy.deepcopy(self.getAuth())
            sdl = SchemaDefLoader(schemaDefObj=shsd, ioObj=self.__ioObj, dbCon=self._dbCon, workPath=self.__sessionPath, cleanUp=False,
                                  warnings='default', verbose=self.__verbose, log=self.__lfh)
            #
            if newTable:
                self.__schemaCreate(schemaDefObj=shsd)
            else:
                for tId, fn in tList:
                    sdl.delete(tId, containerNameList=containerNameList, deleteOpt='selected')

            self.closeConnection()
            #
            if self.__debug:
                self.__lfh.write("\nAuthentication dictionary %r\n" % authD.items())
            #
            mpu = MultiProcUtil(verbose=True, log=self.__lfh)
            mpu.set(workerObj=self, workerMethod="loadBatchFilesWorker")
            mpu.setOptions(authD)
            mpu.setWorkingDir(self.__sessionPath)
            ok, failList, retLists, diagList = mpu.runMulti(dataList=tList, numProc=numProc, numResults=1)

            endTime2 = time.time()
            if self.__verbose:
                self.__lfh.write("\nLoad completed in %.2f seconds\n" % (endTime2 - endTime1))
            return ok
        except:
            traceback.print_exc(file=self.__lfh)
            return False

        endTime = time.time()
        self.__lfh.write("\nCompleted %s %s at %s (%.2f seconds)\n" % (self.__class__.__name__,
                                                                       sys._getframe().f_code.co_name,
                                                                       time.strftime("%Y %m %d %H:%M:%S", time.localtime()),
                                                                       endTime - startTime))

    def loadStatusHistory(self, newTable=False):
        """  Do a full batch load/reload of status history files from the current file source (e.g. archive).
        """
        startTime = time.time()
        self.__lfh.write("\n+StatusHistoryUtils(loadStatusHistory) Starting %s %s at %s\n" % (self.__class__.__name__, sys._getframe().f_code.co_name,
                                                                                              time.strftime("%Y %m %d %H:%M:%S", time.localtime())))
        try:
            pathList = self.getStatusHistoryPathList()
            if self.__verbose:
                self.__lfh.write("\n+StatusHistoryUtils(loadStatusHistory) session %s pathList length %d \n" %
                                 (self.__sessionPath, len(pathList)))
            if len(pathList) < 1:
                return True

            # Create schema and run loader on the input file list --
            #
            self.setResource(resourceName="DA_INTERNAL")
            ok = self.openConnection()
            if ok:
                sd = StatusHistorySchemaDef()
                if newTable:
                    self.__schemaCreate(schemaDefObj=sd)
                #
                sdl = SchemaDefLoader(schemaDefObj=sd, ioObj=self.__ioObj, dbCon=self._dbCon, workPath=self.__sessionPath,
                                      cleanUp=False, warnings='error', verbose=self.__verbose, log=self.__lfh)
                sdl.load(inputPathList=pathList, containerList=None, loadType='batch-file', deleteOpt='all')
                self.closeConnection()
            else:
                if self.__verbose:
                    self.__lfh.write("+StatusHistoryUtils(loadStatusHistory) database connection failed\n")

        except:
            self.closeConnection()
            traceback.print_exc(file=self.__lfh)
            ok = False

        endTime = time.time()
        self.__lfh.write("\n+StatusHistoryUtils(loadStatusHistory) Completed %s %s at %s (%.2f seconds)\n" % (self.__class__.__name__,
                                                                                                              sys._getframe().f_code.co_name,
                                                                                                              time.strftime("%Y %m %d %H:%M:%S", time.localtime()),
                                                                                                              endTime - startTime))
        return ok

    def loadEntryStatusHistory(self, entryIdList):
        """  Load/reload of status history files for the current entry list obtained from the current file source (e.g. archive).
        """
        startTime = time.time()
        self.__lfh.write("\n+StatusHistoryUtils(loadEntryStatusHistory) Starting %s %s at %s\n" % (self.__class__.__name__, sys._getframe().f_code.co_name,
                                                                                                   time.strftime("%Y %m %d %H:%M:%S", time.localtime())))
        try:
            pathList = self.getEntryStatusHistoryPathList(entryIdList)
            if self.__verbose:
                self.__lfh.write("\n+StatusHistoryUtils(loadEntryStatusHistory) session %s path list length %d \n" %
                                 (self.__sessionPath, len(pathList)))
            if len(pathList) < 1:
                return True

            #
            self.setResource(resourceName="DA_INTERNAL")
            ok = self.openConnection()
            if ok:
                sd = StatusHistorySchemaDef()
                sdl = SchemaDefLoader(schemaDefObj=sd, ioObj=self.__ioObj, dbCon=self._dbCon, workPath=self.__sessionPath,
                                      cleanUp=False, warnings='error', verbose=self.__verbose, log=self.__lfh)
                sdl.load(inputPathList=pathList, containerList=None, loadType='batch-insert', deleteOpt='selected')
                self.closeConnection()
            else:
                if self.__verbose:
                    self.__lfh.write("+StatusHistoryUtils(loadEntryStatusHistory) database connection failed\n")

        except:
            self.closeConnection()
            traceback.print_exc(file=self.__lfh)
            ok = False

        endTime = time.time()
        self.__lfh.write("\n+StatusHistoryUtils(loadEntryStatusHistory) Completed %s %s at %s (%.2f seconds)\n" % (self.__class__.__name__,
                                                                                                                   sys._getframe().f_code.co_name,
                                                                                                                   time.strftime("%Y %m %d %H:%M:%S", time.localtime()),
                                                                                                                   endTime - startTime))
        return ok

    def createStatusHistorySchema(self):
        """  Create/recreate status history database schema -
        """
        startTime = time.time()
        self.__lfh.write("\n+StatusHistoryUtils(createStatusHistorySchema) Starting %s %s at %s\n" % (self.__class__.__name__, sys._getframe().f_code.co_name,
                                                                                                      time.strftime("%Y %m %d %H:%M:%S", time.localtime())))
        try:
            # Create status history database schema
            #
            self.setResource(resourceName="DA_INTERNAL")
            ok = self.openConnection()
            if ok:
                sd = StatusHistorySchemaDef()
                self.__schemaCreate(schemaDefObj=sd)
                self.closeConnection()
            else:
                if self.__verbose:
                    self.__lfh.write("+StatusHistoryUtils(createStatusHistorySchema) database connection failed\n")

        except:
            self.closeConnection()
            traceback.print_exc(file=self.__lfh)
            ok = False

        endTime = time.time()
        self.__lfh.write("\n+StatusHistoryUtils(createStatusHistorySchema) Completed %s %s at %s (%.2f seconds)\n" % (self.__class__.__name__,
                                                                                                                      sys._getframe().f_code.co_name,
                                                                                                                      time.strftime("%Y %m %d %H:%M:%S", time.localtime()),
                                                                                                                      endTime - startTime))
        return ok

    def updateEntryStatusHistory(self, entryIdList, statusCode, annotatorInitials, details="Update by status module", statusCodePrior=None):
        """  Update status history files from the input entry list obtained from the current file source (e.g. archive)
             with the input (statusCode, annotatorInitials, and details).

             Use the priorStatusCode to detect missing history records for the special case of ['AUCO','REPL'] where
             an additional status record is inserted using a time stamp inferred from the modification date of a model milestone file.


        """
        startTime = time.time()
        self.__lfh.write("\n\n+StatusHistoryUtils(updateEntryStatusHistory) Starting %s %s at %s\n" % (self.__class__.__name__, sys._getframe().f_code.co_name,
                                                                                                       time.strftime("%Y %m %d %H:%M:%S", time.localtime())))
        okSh = False
        # Skip conditions --
        #
        self.__lfh.write("\n\n+StatusHistoryUtils(updateEntryStatusHistory) entryIdList %r statusCode %r annotatorInitials %r statusCodePrior %r\n" %
                         (entryIdList, statusCode, annotatorInitials, statusCodePrior))
        if ((entryIdList is None) or (len(entryIdList) < 1) or (statusCode is None) or (annotatorInitials is None) or (statusCode in ['AUCO', 'REPL'])):
            self.__lfh.write("\n\n+StatusHistoryUtils(updateEntryStatusHistory) SKIPPED UPDATE with entryIdList %r statusCode %r annotatorInitials %r\n" %
                             (entryIdList, statusCode, annotatorInitials))
            return okSh
        try:
            for entryId in entryIdList:
                # This section performs the status history file update -
                sH = StatusHistory(siteId=self.__siteId, fileSource='archive', sessionPath=self.__sessionPath, verbose=self.__verbose, log=self.__lfh)
                sH.setEntryId(entryId, pdbId=None, inpPath=None, overWrite=False)
                statusHistoryCodeLast, statusHistoryDateLast = sH.getLastStatusAndDate()
                if (self.__verbose):
                    self.__lfh.write("\n\n+StatusHistoryUtils(updateEntryStatusHistory) entryId %r statusHistoryCodeLast %r statusHistoryDateLast %r statusCode %r statusCodePrior %r\n" %
                                     (entryId, statusHistoryCodeLast, statusHistoryDateLast, statusCode, statusCodePrior))
                #
                if ((statusCodePrior in ['AUCO', 'REPL']) and (statusCodePrior != statusHistoryCodeLast)):
                    # Get the modification date for the last model file  milestone = deposit -
                    revStepDate = self.__getModelFileTimeStamp(entryId, versionId="latest", mileStone='deposit', defValue=None)
                    if self.__verbose:
                        self.__lfh.write("+StatusHistoryUtils.updateEntryStatusHistory() %s model file (deposit) timestamp = revStepDate %r\n" % (entryId, revStepDate))
                    if ((statusHistoryCodeLast is not None) and (revStepDate is not None)):
                        sH.add(statusCodeBegin=statusHistoryCodeLast, dateBegin=statusHistoryDateLast,
                               statusCodeEnd=statusCodePrior, dateEnd=revStepDate,
                               annotator=annotatorInitials, details="Automated revision or correction entry")
                elif ((statusCodePrior is not None) and (statusCodePrior != statusHistoryCodeLast)):
                    # there is some missing prior status history record so insert a modified comment
                    details += " (detected status history record) "
                #
                okSh = sH.nextRecord(statusCodeNext=statusCode, dateNext=None, annotator=annotatorInitials, details=details)
                if okSh:
                    okSh = sH.store(entryId, outPath=None, versionId='latest')
                if (self.__verbose):
                    self.__lfh.write("+StatusHistoryUtils(updateEntryStatusHistory) %s status history file update returns status %r\n" % (entryId, okSh))
        except:
            self.__lfh.write("+StatusHistoryUtils(updateEntryStatusHistory) failed with exception for %r\n" % entryIdList)
            traceback.print_exc(file=self.__lfh)
            okSh = False

        endTime = time.time()
        self.__lfh.write("\n+StatusHistoryUtils(updateEntryStatusHistory) Completed %s %s at %s (%.2f seconds)\n" % (self.__class__.__name__,
                                                                                                                   sys._getframe().f_code.co_name,
                                                                                                                   time.strftime("%Y %m %d %H:%M:%S", time.localtime()),
                                                                                                                   endTime - startTime))
        return okSh
