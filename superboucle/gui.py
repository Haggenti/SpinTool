#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Gui
"""
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QMainWindow, QFileDialog,
                             QAction, QActionGroup, QMessageBox, QApplication)
from PyQt5.QtCore import QTimer, QObject, pyqtSignal, QSettings, Qt, QUrl
from superboucle.clip import Clip, load_song_from_file, verify_ext, Song
from superboucle.gui_ui import Ui_MainWindow
from superboucle.cell import Cell
from superboucle.learn import LearnDialog
from superboucle.device_manager import ManageDialog
from superboucle.playlist import PlaylistDialog
from superboucle.scene_manager import SceneManager
from superboucle.song_annotation import SongAnnotation
from superboucle.preferences import Preferences
from superboucle.about import About
from superboucle.port_manager import PortManager
from superboucle.new_song import NewSongDialog
from superboucle.add_clip import AddClipDialog
from superboucle.add_port import AddPortDialog
from superboucle.device import Device
import struct
from queue import Queue, Empty
import pickle
from os.path import expanduser, dirname, isfile
import numpy as np
import soundfile as sf
import math
import time
import copy

BAR_START_TICK = 0.0
BEATS_PER_BAR = 4.0
BEAT_TYPE = 4.0
TICKS_PER_BEAT = 960.0

APP_VERSION = "v 20.04.18"
WIKI_LINK = "https://github.com/manucontrovento/SpinTool/wiki"

class Gui(QMainWindow, Ui_MainWindow):
    NOTEON = 0x9
    NOTEOFF = 0x8
    MIDICTRL = 11

    GREEN = ("#cell_frame { border: 0px; border-radius: 10px; "
             "background-color: rgb(125,242,0);}")
    BLUE = ("#cell_frame { border: 0px; border-radius: 10px; "
            "background-color: rgb(0, 130, 240);}")
    RED = ("#cell_frame { border: 0px; border-radius: 10px; "
           "background-color: rgb(255, 21, 65);}")
    AMBER = ("#cell_frame { border: 0px; border-radius: 10px; "
             "background-color: rgb(255, 102, 0);}")
    PURPLE = ("#cell_frame { border: 0px; border-radius: 10px; "
              "background-color: rgb(130, 0, 240);}")
    DEFAULT = ("#cell_frame { border: 0px; border-radius: 10px; "
               "background-color: rgb(217, 217, 217);}")

    RECORD_BLINK = ("QPushButton {background-color: rgb(255, 255, 255);}"
                    "QPushButton:pressed {background-color: "
                    "rgb(98, 98, 98);}")

    RECORD_DEFAULT = ("QPushButton {background-color: rgb(0, 0, 0);}"
                      "QPushButton:pressed {background-color: "
                      "rgb(98, 98, 98);}")

    STATE_COLORS = {Clip.STOP: RED,
                    Clip.STARTING: GREEN,
                    Clip.START: GREEN,
                    Clip.STOPPING: RED,
                    Clip.PREPARE_RECORD: AMBER,
                    Clip.RECORDING: AMBER}
    STATE_BLINK = {Clip.STOP: False,
                   Clip.STARTING: True,
                   Clip.START: False,
                   Clip.STOPPING: True,
                   Clip.PREPARE_RECORD: True,
                   Clip.RECORDING: False}

    BLINK_DURATION = 200
    PROGRESS_PERIOD = 300

    ADD_PORT_LABEL = 'Add new Port...'

    updateUi = pyqtSignal()
    readQueueIn = pyqtSignal()
    updatePorts = pyqtSignal()
    songLoad = pyqtSignal()

    def __init__(self, song, jack_client, app):
        QObject.__init__(self)
        super(Gui, self).__init__()
        self._jack_client = jack_client
        self.app = app
        self.setupUi(self)
        self.clip_volume.knobRadius = 3
        self.is_learn_device_mode = False
        self.queue_out, self.queue_in = Queue(), Queue()
        self.updateUi.connect(self.update)
        self.readQueueIn.connect(self.readQueue)
        self.current_vol_block = 0
        self.last_clip = None
        self.memory_clip = None
        self.songAnnotationDialog = None # Annotation window
        self.scenesManagerDialog = None
        self.current_scene = None

        # Load devices
        self.deviceGroup = QActionGroup(self.menuDevice)
        self.devices = []
        device_settings = QSettings(Preferences.COMPANY, Preferences.DEVICES)
        
        if ((device_settings.contains('devices')
             and device_settings.value('devices'))):
            for raw_device in device_settings.value('devices'):
                self.devices.append(Device(pickle.loads(raw_device)))
        else:
            self.devices.append(Device({'name': 'No Device'}))
            
        self.updateDevices()
        self.deviceGroup.triggered.connect(self.onDeviceSelect)
        
        self.settings = QSettings(Preferences.COMPANY, Preferences.APPLICATION)
        # Qsetting appear to serialize empty lists as @QInvalid
        # which is then read as None :(

        # Load playlist
        self.playlist = self.settings.value('playlist', []) or []
        # Load paths
        self.paths_used = self.settings.value('paths_used', {})
        
        print("Loading preferences")
        
        # Load preferences
        self.auto_connect = self.settings.value('auto_connect','true') == "true"
        self.show_clip_details_on_trigger = self.settings.value('show_clip_details_on_trigger','false') == "true"
        self.show_clip_details_on_volume = self.settings.value('show_clip_details_on_volume','false') == "true"
        self.play_clip_after_record = self.settings.value('play_clip_after_record','false') == "true"     
        self.show_scenes_on_start = self.settings.value('show_scenes_on_start','false') == 'true'
        self.show_playlist_on_start = self.settings.value('show_playlist_on_start','false') == 'true'
        self.show_song_annotation_on_load = self.settings.value('show_song_annotation_on_load','false') == 'true'
        # and windows position
        self.playlist_geometry = self.settings.value('playlist_geometry', None)
        self.scenes_geometry = self.settings.value('scenes_geometry', None)
        self.gui_geometry = self.settings.value('gui_geometry', None)
        self.song_annotation_geometry = self.settings.value('song_annotation_geometry', None)

        # Load song
        self.port_by_name = {}
        self.initUI(song)

        self.actionNew.triggered.connect(self.onActionNew)
        self.actionOpen.triggered.connect(self.onActionOpen)
        self.actionSave.triggered.connect(self.onActionSave)
        self.actionSave_As.triggered.connect(self.onActionSaveAs)
        self.actionQuit.triggered.connect(self.onActionQuit)
        self.actionAdd_Device.triggered.connect(self.onAddDevice)
        self.actionManage_Devices.triggered.connect(self.onManageDevice)
        self.actionPreferences.triggered.connect(self.onPreferences)
        self.actionPlaylist_Editor.triggered.connect(self.onPlaylistEditor)
        self.actionScene_Manager.triggered.connect(self.onSceneManager)
        self.actionPort_Manager.triggered.connect(self.onPortManager)
        self.actionFullScreen.triggered.connect(self.onActionFullScreen)
        self.actionAbout.triggered.connect(self.onActionAbout)
        self.actionOnline_Wiki.triggered.connect(self.onActionWiki)
        self.action_SongAnnotation.triggered.connect(self.onAction_SongAnnotation)
        self.master_volume.valueChanged.connect(self.onMasterVolumeChange)
        self.bpm.valueChanged.connect(self.onBpmChange)
        self.beat_per_bar.valueChanged.connect(self.onBeatPerBarChange)
        self.rewindButton.clicked.connect(self.onRewindClicked)
        self.playButton.clicked.connect(self._jack_client.transport_start)
        self.pauseButton.clicked.connect(self._jack_client.transport_stop)
        self.gotoButton.clicked.connect(self.onGotoClicked)
        self.recordButton.clicked.connect(self.onRecord)
        self.clip_name.textChanged.connect(self.onClipNameChange)
        self.clip_volume.valueChanged.connect(self.onClipVolumeChange)
        self.beat_diviser.valueChanged.connect(self.onBeatDiviserChange)
        self.output.activated.connect(self.onOutputChange)
        self.mute_group.valueChanged.connect(self.onMuteGroupChange)
        self.one_shot_clip.stateChanged.connect(self.onOneShotClip)
        self.lock_record.stateChanged.connect(self.onLockRecord)
        self.frame_offset.valueChanged.connect(self.onFrameOffsetChange)
        self.beat_offset.valueChanged.connect(self.onBeatOffsetChange)
        self.revertButton.clicked.connect(self.onRevertClip)
        self.normalizeButton.clicked.connect(self.onNormalizeClip)
        self.exportButton.clicked.connect(self.onExportClip)
        self.deleteButton.clicked.connect(self.onDeleteClipClicked)
        self.btnCopy.clicked.connect(self.onCopyDetailsClicked)
        self.btnPaste.clicked.connect(self.onPasteDetailsClicked)

        self.blktimer = QTimer()
        self.blktimer.state = False
        self.blktimer.timeout.connect(self.toggleBlinkButton)
        self.blktimer.start(self.BLINK_DURATION)

        self.disptimer = QTimer()
        self.disptimer.start(self.PROGRESS_PERIOD)
        self.disptimer.timeout.connect(self.updateProgress)

        self._jack_client.set_timebase_callback(self.timebase_callback)

        if self.gui_geometry:
            self.restoreGeometry(self.gui_geometry)        
        
        self.show()

        # showing additional windows if desired:
        
        if self.show_scenes_on_start == True:
            self.onSceneManager()
            
        if self.show_playlist_on_start == True:
            self.onPlaylistEditor()
        
       
    def initUI(self, new_song, loading = True):

        # remove old buttons
        self.btn_matrix = [[None for y in range(new_song.height)]
                           for x in range(new_song.width)]
        self.state_matrix = [[-1 for y in range(new_song.height)]
                             for x in range(new_song.width)]

        for i in reversed(range(self.gridLayout.count())):
            self.gridLayout.itemAt(i).widget().close()
            self.gridLayout.itemAt(i).widget().setParent(None)

        # first pass without removing old ports
        self.updateJackPorts(new_song, remove_ports=False)
               
        self.song = new_song

        if self.songAnnotationDialog:
             # Not a nice way but it's the only one I found:
            self.songAnnotationDialog.updateText(self.song.annotation)  

        # second pass with removing
        self.updateJackPorts(new_song, remove_ports=True)
        self.output.clear()
        self.output.addItems(new_song.outputsPorts)
        self.output.addItem(Gui.ADD_PORT_LABEL)
        self.master_volume.setValue(new_song.volume * 256)
        self.updateMasterVolumeValue()
        self.bpm.setValue(new_song.bpm)
        self.beat_per_bar.setValue(new_song.beat_per_bar)
        for x in range(new_song.width):
            for y in range(new_song.height):
                clip = new_song.clips_matrix[x][y]
                cell = Cell(self, clip, x, y)
                self.btn_matrix[x][y] = cell
                self.gridLayout.addWidget(cell, y, x)

        if loading == True:

            # send device init command
            for init_cmd in self.device.init_command:
                self.queue_out.put(init_cmd)
    
            self.setWindowTitle("SpinTool - {} - {}".format(APP_VERSION, new_song.file_name or "Empty Song"))
            self.labelRecording.setVisible(False)
    
            if self.song.initial_scene in self.song.scenes:
                self.song.loadScene(self.song.initial_scene)

                # Lighting up initial scenes button:
                self.updateScenesButtons(self.song.initial_scene)
        
        self.update()
        
        if self.device:
            time.sleep(0.5) # wait for all init and light signals to be processed by controller
            
        self.songLoad.emit()

    def ApplicationVersion(self):
        return APP_VERSION

    def openSongFromDisk(self, file_name):
        self._jack_client.transport_stop()
        self._jack_client.transport_locate(0)

        message = QMessageBox(self)
        message.setWindowTitle("Loading ....")
        message.setText("Reading Files, please wait ...")
        message.show()
        self.initUI(load_song_from_file(file_name))
        message.close()

        self.redraw()
              
        if self.show_song_annotation_on_load:
            
            if self.songAnnotationDialog:
                self.songAnnotationDialog.close()
                self.songAnnotationDialog.destroy()
                
            self.showSongAnnotation()

    def showSongAnnotation(self):
        self.songAnnotationDialog = SongAnnotation(self)
        self.action_SongAnnotation.setEnabled(False)

    def moveEvent(self, event):
        self.gui_geometry = self.saveGeometry()

    def closeEvent(self, event):
        self.onApplicationExit()
    
    def onApplicationExit(self):
        self.gui_geometry = self.saveGeometry()
        
        #device lights turn off, if exhisting. Prevents device from remaining lighted-up
        try:
            self.lightDownDevice()
            print("device light off")
        except:
            print("no device connected")  # Could not turn off device lights
        time.sleep(1)
        # Sorry for this bad coding. But I tried in all other ways, if you don't wait a while to let
        # the engine processal pending midi messages, the device doesn't light off.
        
        device_settings = QSettings(Preferences.COMPANY, Preferences.DEVICES)
        device_settings.setValue('devices', 
                                 [pickle.dumps(x.mapping)
                                  for x in self.devices])
        
        self.settings.setValue('playlist', self.playlist)
        self.settings.setValue('paths_used', self.paths_used)
        
        print("Saving preferences")
        # Saving preferences
        self.settings.setValue('auto_connect', self.auto_connect)
        self.settings.setValue('show_clip_details_on_trigger', self.show_clip_details_on_trigger)
        self.settings.setValue('show_clip_details_on_volume', self.show_clip_details_on_volume)
        self.settings.setValue('play_clip_after_record', self.play_clip_after_record)
        self.settings.setValue('show_scenes_on_start', self.show_scenes_on_start)
        self.settings.setValue('show_playlist_on_start', self.show_playlist_on_start)
        self.settings.setValue('show_song_annotation_on_load', self.show_song_annotation_on_load)

        # and windows position
        self.settings.setValue("gui_geometry", self.gui_geometry)
        self.settings.setValue("scenes_geometry", self.scenes_geometry)
        self.settings.setValue("playlist_geometry", self.playlist_geometry)
        self.settings.setValue("song_annotation_geometry", self.song_annotation_geometry)
        
        self.settings.sync()
        print("Preferences saved")
              
    def onStartStopClicked(self):
        clip = self.sender().parent().parent().clip
        self.startStop(clip.x, clip.y)

    def startStop(self, x, y):
        clip = self.btn_matrix[x][y].clip # affected clip
        
        if clip is None:
            return

        if self.song.is_record:
            if clip.lock_rec == True:
                # Can't record on this clip:
                print("This clip is LOCKED for recording")
                
            else:
                self.song.is_record = False
                self.updateRecordBtn()
                # calculate buffer size
                state, position = self._jack_client.transport_query()
                bps = position['beats_per_minute'] / 60
                fps = position['frame_rate']
                size = int((1 / bps) * clip.beat_diviser * fps)
                self.song.init_record_buffer(clip, 2, size, fps)
                # set frame offset based on jack block size
                clip.frame_offset = self._jack_client.blocksize
                clip.state = Clip.PREPARE_RECORD
                self.recordButton.setStyleSheet(self.RECORD_DEFAULT)
        else:
            self.song.toggle(clip.x, clip.y)
            
            # to automatically view clip details, when triggered:
            if self.show_clip_details_on_trigger:
                self.last_clip = clip
                self.updateClipInfo()  
            
        self.update()

    def updateClipInfo(self, updateDetailsOnly = False):
                
        if self.last_clip:
            self.frame_clip.setEnabled(True)
            self.clip_name.setText(self.last_clip.name)
            self.frame_offset.setValue(self.last_clip.frame_offset)
            self.beat_offset.setValue(self.last_clip.beat_offset)
            self.beat_diviser.setValue(self.last_clip.beat_diviser)
            self.output.setCurrentText(self.last_clip.output)
            self.mute_group.setValue(self.last_clip.mute_group)
            self.clip_volume.setValue(self.last_clip.volume * 256)
            self.updateClipVolumeValue()
            self.one_shot_clip.setChecked(self.last_clip.one_shot)
            self.lock_record.setChecked(self.last_clip.lock_rec)
            
            if (updateDetailsOnly == False):
            
                state, position = self._jack_client.transport_query()
                fps = position['frame_rate']
                bps = self.bpm.value() / 60
                if self.bpm.value() and fps:
                    size_in_beat = (bps / fps) * self.song.length(self.last_clip)
                else:
                    size_in_beat = "No BPM info"
    
                # Showing file name too:
                clip_description = ("Size in sample: %s\nSize in beat: %s\nFile name: %s"
                    % (self.song.length(self.last_clip),
                       round(size_in_beat, 1),
                       self.last_clip.audio_file))
    
                self.clip_description.setText(clip_description)

    def onEdit(self):
        self.last_clip = self.sender().parent().parent().clip
        
        self.updateClipInfo()

    def onAddClipClicked(self):
        cell = self.sender().parent().parent()
        if QApplication.keyboardModifiers() == Qt.ControlModifier:
            cell.setClip(cell.openClip())
        else:
            AddClipDialog(self, cell)
            # TODO: one day, find a way to show clip details in this Else as well.
        
        self.updateClipInfo()

    def onRevertClip(self):
        if self.last_clip and self.last_clip.audio_file:
            audio_file = self.last_clip.audio_file
            self.song.data[audio_file] = self.song.data[audio_file][::-1]

    def onNormalizeClip(self):
        if self.last_clip and self.last_clip.audio_file:
            audio_file = self.last_clip.audio_file
            absolute_val = np.absolute(self.song.data[audio_file])
            current_level = np.ndarray.max(absolute_val)
            self.song.data[audio_file][:] *= (1 / current_level)

    def onExportClip(self):
        if self.last_clip and self.last_clip.audio_file:
            audio_file = self.last_clip.audio_file
            file_name, a = self.getSaveFileName(
                'Export Clip : %s' % self.last_clip.name, 'WAVE (*.wav)')

            if file_name:
                file_name = verify_ext(file_name, 'wav')
                sf.write(file_name, self.song.data[audio_file],
                         self.song.samplerate[audio_file],
                         subtype=sf.default_subtype('WAV'),
                         format='WAV')

    def onDeleteClipClicked(self):
        if self.last_clip:
            response = QMessageBox.question(self,
                                            "Delete Clip?",
                                            ("Are you sure to delete the clip?"))
            if response == QMessageBox.Yes:
                #self.frame_clip.setEnabled(False)
                self.song.removeClip(self.last_clip)
                self.initUI(self.song, False)

    def updateMasterVolumeValue(self):
        self.labelMasterVolume.setText(str(math.trunc(self.song.volume * 100)))  # showing volume numeric value

    def onMasterVolumeChange(self):
        self.song.volume = (self.master_volume.value() / 256)
        self.updateMasterVolumeValue()

    def onBpmChange(self):
        self.song.bpm = self.bpm.value()

    def onBeatPerBarChange(self):
        self.song.beat_per_bar = self.beat_per_bar.value()

    def onGotoClicked(self):
        state, position = self._jack_client.transport_query()
        new_position = (position['beats_per_bar']
                        * (self.gotoTarget.value() - 1)
                        * position['frame_rate']
                        * (60 / position['beats_per_minute']))
        self._jack_client.transport_locate(int(round(new_position, 0)))

    def onRecord(self):
        self.song.is_record = not self.song.is_record
        #self.labelRecording.setVisible(self.song.is_record)
        self.updateRecordBtn()

    def updateRecordBtn(self):
        self.labelRecording.setVisible(self.song.is_record)
        
        if not self.song.is_record:
            self.recordButton.setStyleSheet(self.RECORD_DEFAULT)
        if self.device.record_btn:
            (msg_type, channel, pitch, velocity) = self.device.record_btn
            if self.song.is_record:
                if self.settings.value('rec_color', Preferences.COLOR_AMBER) == Preferences.COLOR_AMBER:
                    color = self.device.blink_amber_vel
                else:
                    color = self.device.blink_red_vel
            else:
                color = self.device.black_vel
            self.queue_out.put(((msg_type << 4) + channel, pitch, color))

    def onRewindClicked(self):
        self._jack_client.transport_locate(0)

    def onClipNameChange(self):
        self.last_clip.name = self.clip_name.text()
        cell = self.btn_matrix[self.last_clip.x][self.last_clip.y]
        cell.clip_name.setText(self.last_clip.name)

    def updateClipVolumeValue(self):
        self.labelClipVolume.setText(str(math.trunc(self.last_clip.volume * 100)))  # Showing numeric clip volume

    def onClipVolumeChange(self):
        if self.last_clip:
            self.last_clip.volume = (self.clip_volume.value() / 256)
            self.updateClipVolumeValue()

    def onBeatDiviserChange(self):
        if self.last_clip:
            self.last_clip.beat_diviser = self.beat_diviser.value()

    def onOutputChange(self):
        new_port = self.output.currentText()
        if new_port == Gui.ADD_PORT_LABEL:
            AddPortDialog(self)
        else:
            if self.last_clip:
                self.last_clip.output = new_port

    def addPort(self, name):
        self.song.outputsPorts.add(name)
        self.updateJackPorts(self.song)
        if self.output.findText(name) == -1:
            self.output.insertItem(self.output.count() - 1, name)
        if self.last_clip:
            self.last_clip.output = name
            self.output.setCurrentText(name)

    def removePort(self, name):
        if name != Clip.DEFAULT_OUTPUT:
            self.song.outputsPorts.remove(name)
            for c in self.song.clips:
                if c.output == name:
                    c.output = Clip.DEFAULT_OUTPUT
            self.updateJackPorts(self.song)
            self.output.removeItem(self.output.findText(name))
            if self.last_clip:
                self.output.setCurrentText(self.last_clip.output)

    def updateJackPorts(self, song, remove_ports=True):
        '''Update jack port based on clip output settings
        update dict containing ports with shortname as key'''

        current_ports = set()
        for port in self._jack_client.outports:
            current_ports.add(port.shortname)

        wanted_ports = set()
        for port_basename in song.outputsPorts:
            for ch in Song.CHANNEL_NAMES:
                port = Song.CHANNEL_NAME_PATTERN.format(port=port_basename,
                                                        channel=ch)
                wanted_ports.add(port)

        # remove unwanted ports
        if remove_ports:
            port_to_remove = []
            for port in self._jack_client.outports:
                if port.shortname not in wanted_ports:
                    current_ports.remove(port.shortname)
                    port_to_remove.append(port)
            for port in port_to_remove:
                port.unregister()

        # create new ports
        for new_port_name in wanted_ports - current_ports:
            self._jack_client.outports.register(new_port_name)

        self.port_by_name = {port.shortname: port
                             for port in self._jack_client.outports}

        self.updatePorts.emit()

    def onCopyDetailsClicked(self):
        if self.last_clip:
            self.memory_clip = copy.deepcopy(self.last_clip)
        
    def onPasteDetailsClicked(self):
        if self.last_clip and self.memory_clip:

            self.last_clip.volume = self.memory_clip.volume
            self.last_clip.frame_offset = self.memory_clip.frame_offset
            self.last_clip.beat_offset = self.memory_clip.beat_offset
            self.last_clip.beat_diviser = self.memory_clip.beat_diviser
            self.last_clip.output = self.memory_clip.output
            self.last_clip.mute_group = self.memory_clip.mute_group
            self.last_clip.one_shot = self.memory_clip.one_shot
            self.last_clip.lock_rec = self.memory_clip.lock_rec
            self.last_clip.shot = False
            
            self.updateClipInfo(True)

    def onOneShotClip(self):
        if self.last_clip:
            self.last_clip.one_shot = self.one_shot_clip.isChecked()

    def onLockRecord(self):
        if self.last_clip:
            self.last_clip.lock_rec  = self.lock_record.isChecked()

    def onMuteGroupChange(self):
        if self.last_clip:
            self.last_clip.mute_group = self.mute_group.value()

    def onFrameOffsetChange(self):
        if self.last_clip:
            self.last_clip.frame_offset = self.frame_offset.value()

    def onBeatOffsetChange(self):
        if self.last_clip:
            self.last_clip.beat_offset = self.beat_offset.value()

    def onActionNew(self):
        NewSongDialog(self)

    def getOpenFileName(self, title, file_type, parent=None,
                        dialog=QFileDialog.getOpenFileName):
        path = self.paths_used.get(file_type, expanduser('~'))
        file_name, a = dialog(parent or self, title, path, file_type)
        if a and file_name:
            if isinstance(file_name, list):
                self.paths_used[file_type] = dirname(file_name[0])
            else:
                self.paths_used[file_type] = dirname(file_name)
        return file_name, a

    def getSaveFileName(self, *args):
        return self.getOpenFileName(*args, dialog=QFileDialog.getSaveFileName)

    def onActionOpen(self):
        file_name, a = self.getOpenFileName('Open Song',
                                            'SpinTool Song (*.sbs)')
        if a and file_name and self.checkFileExists(file_name):
            self.openSongFromDisk(file_name)
        else:
            print("File not found or no song selected")

    def checkFileExists(self, file_name):
        return isfile(file_name)

    def onActionSave(self):
        if self.song.file_name:
            self.song.save()
        else:
            self.onActionSaveAs()

    def onActionSaveAs(self):
        file_name, a = self.getSaveFileName('Save Song',
                                            'SpinTool Song (*.sbs)')

        if file_name:
            file_name = verify_ext(file_name, 'sbs')
            self.song.file_name = file_name
            self.song.save()
            print("File saved to : {}".format(self.song.file_name))

    def onActionQuit(self):
        self.onApplicationExit()
        self.app.quit()

    def onAddDevice(self):
        self.learn_device = LearnDialog(self, self.addDevice)
        self.is_learn_device_mode = True

    def onPreferences(self):
        Preferences(self) # Preferences Dialog

    def onManageDevice(self):
        ManageDialog(self)

    def onPlaylistEditor(self):
        PlaylistDialog(self)
        self.actionPlaylist_Editor.setEnabled(False)

    def onSceneManager(self):
        self.scenesManagerDialog = SceneManager(self)
        if self.current_scene:
            self.scenesManagerDialog.selectItem(self.getSceneIndex(self.current_scene))
        else:
            self.scenesManagerDialog.selectItem(0)
        self.actionScene_Manager.setEnabled(False)

    def onPortManager(self):
        PortManager(self)
        self.actionPort_Manager.setEnabled(False)

    def onActionAbout(self):
        About(self)
    
    def onActionShowConsole(self):
	    self.showConsoleText()
        
    def onActionWiki(self): 
        QDesktopServices.openUrl(QUrl(WIKI_LINK))
        
    def onAction_SongAnnotation(self):
        self.showSongAnnotation()

    def onActionFullScreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.show()

    def update(self):
        for x in range(len(self.song.clips_matrix)):
            line = self.song.clips_matrix[x]
            for y in range(len(line)):
                clp = line[y]
                if clp is None:
                    state = None
                else:
                    state = clp.state
                if state != self.state_matrix[x][y]:
                    if clp:
                        self.btn_matrix[x][y].setColor(state)
                    try:                                            
                        self.queue_out.put(self.device.generateNote(x,
                                                                    y,
                                                                    state))
                    except IndexError:
                        # print("No cell associated to %s x %s"
                        # % (clp.x, clp.y))
                        pass
                self.state_matrix[x][y] = state

    def lightDownDevice(self):
        self.device.setAllCellsColor(self.queue_out, self.device.black_vel)
        
    def redraw(self):
        self.state_matrix = [[-1 for x in range(self.song.height)]
                             for x in range(self.song.width)]
        self.update()

    def readQueue(self):
        try:
            while True:
                note = self.queue_in.get(block=False)
                if len(note) == 3:
                    status, pitch, vel = struct.unpack('3B', note)
                    channel = status & 0xF
                    msg_type = status >> 4
                    self.processNote(msg_type, channel, pitch, vel)
                    # else:
                    # print("Invalid message length")
        except Empty:
            pass

    def getSceneIndex(self, i_scene):
        index = 0
        for i in range(len(self.device.scene_buttons)):
            if i == i_scene:
                return index
            index += 1
                    

    def processNote(self, msg_type, channel, pitch, vel):

        btn_id = (msg_type, channel, pitch, vel)
        btn_id_vel = (msg_type, channel, pitch, -1)
        ctrl_key = (msg_type, channel, pitch)

        # master volume
        if ctrl_key == self.device.master_volume_ctrl:
            self.song.volume = vel / 127
            self.updateMasterVolumeKnob()
            (self.master_volume
             .setValue(self.song.master_volume * 256))
            
        elif self.device.play_btn in [btn_id, btn_id_vel]:
            self._jack_client.transport_start()
            
            (a, b_channel, b_pitch, b) = self.device.play_btn
            note = ((a << 4) + b_channel, b_pitch, self.device.green_vel)
            self.queue_out.put(note)
            
            (a, b_channel, b_pitch, b) = self.device.pause_btn
            note = ((a << 4) + b_channel, b_pitch, self.device.black_vel)
            self.queue_out.put(note)
            
        elif self.device.pause_btn in [btn_id, btn_id_vel]:
            self._jack_client.transport_stop()
            
            (a, b_channel, b_pitch, b) = self.device.play_btn
            note = ((a << 4) + b_channel, b_pitch, self.device.black_vel)
            self.queue_out.put(note)
            
            (a, b_channel, b_pitch, b) = self.device.pause_btn
            if self.settings.value('rec_color', Preferences.COLOR_AMBER) == Preferences.COLOR_AMBER:
                color = self.device.red_vel
            else:
                color = self.device.amber_vel
            note = ((a << 4) + b_channel, b_pitch, color)
            self.queue_out.put(note)            
            
        elif self.device.rewind_btn in [btn_id, btn_id_vel]:
            self.onRewindClicked()
            
        elif self.device.goto_btn in [btn_id, btn_id_vel]:
            self.onGotoClicked()
            
        elif self.device.record_btn in [btn_id, btn_id_vel]:
            self.onRecord()   # button control color managed in: updateRecordBtn
            
        # volume control knobs
        elif ctrl_key in self.device.ctrls:
            try:
                ctrl_index = self.device.ctrls.index(ctrl_key)
                clip = (self.song.clips_matrix
                        [ctrl_index]
                        [self.current_vol_block])
                if clip:
                    clip.volume = vel / 127
                    if self.last_clip == clip:
                        self.clip_volume.setValue(self.last_clip.volume * 256)
                    elif self.show_clip_details_on_volume:
                        self.last_clip = clip
                        self.updateClipInfo()   
            except KeyError:
                pass
            
        # Scenes
        elif (btn_id in self.device.scene_buttons
              or btn_id_vel in self.device.scene_buttons):
            try:
                scene_id = self.device.scene_buttons.index(btn_id)
                self.current_scene = (self.device.scene_buttons.index(btn_id))
            except ValueError:
                scene_id = self.device.scene_buttons.index(btn_id_vel)
                self.current_scene = (self.device.scene_buttons.index(btn_id_vel))
            
            sceneExhists = True

            try:
                self.song.loadSceneId(scene_id)
                self.update()

            except IndexError:
                print('cannot load scene {} - there are only {} scenes.'
                      ''.format(scene_id, len(self.song.scenes)))
                sceneExhists = False

            if sceneExhists == True:
                # buttons are updated and scene button is lighted on just if scene exhists:
                for i in range(len(self.device.scene_buttons)):
                    (a, b_channel, b_pitch, b) = self.device.scene_buttons[i]
                    if i == self.current_scene:
                        color = self.device.green_vel
                    else:
                        color = self.device.black_vel
                        
                    self.queue_out.put(((self.NOTEON << 4) + b_channel, b_pitch, color))
                    time.sleep(0.01)
                
                if self.scenesManagerDialog:
                    self.scenesManagerDialog.selectItem(self.current_scene)
                
        # Line blocks 
        elif (btn_id in self.device.block_buttons
              or btn_id_vel in self.device.block_buttons):
            try:
                self.current_vol_block = (self.device.block_buttons.index(btn_id))
            except ValueError:
                self.current_vol_block = (self.device.block_buttons.index(btn_id_vel))
                
            for i in range(len(self.device.block_buttons)):
                (a, b_channel, b_pitch, b) = self.device.block_buttons[i]
                if i == self.current_vol_block:
                    color = self.device.green_vel                                
                else:
                    color = self.device.black_vel
                self.queue_out.put(((self.NOTEON << 4) + b_channel, b_pitch, color))
        else:
            x, y = -1, -1
            try:
                x, y = self.device.getXY(btn_id)
            except IndexError:
                pass
            except KeyError:
                try:
                    x, y = self.device.getXY(btn_id_vel)
                except KeyError:
                    pass

            if (x >= 0 and y >= 0):
                self.startStop(x, y)

    def updateScenesButtons(self, scene):
        if self.device and scene:
            
            index = 0
            for i, enScene in enumerate(self.song.scenes):
                if enScene == scene:
                    index = i

            for i in range(len(self.device.scene_buttons)):
                (a, b_channel, b_pitch, b) = self.device.scene_buttons[i]
                if index == i:  
                    color = self.device.green_vel 
                else:
                    color = self.device.black_vel
                self.queue_out.put(((self.NOTEON << 4) + b_channel, b_pitch, color))

    def toggleBlinkButton(self):
        for line in self.btn_matrix:
            for btn in line:
                if btn.blink:
                    if self.blktimer.state:
                        btn.setStyleSheet(btn.color)
                    else:
                        btn.setStyleSheet(self.DEFAULT)
        if self.song.is_record:
            if self.blktimer.state:
                self.recordButton.setStyleSheet(self.RECORD_BLINK)
            else:
                self.recordButton.setStyleSheet(self.RECORD_DEFAULT)

        self.blktimer.state = not self.blktimer.state

    def updateProgress(self):
        state, pos = self._jack_client.transport_query()
        if 'bar' in pos:
            bbt = "%d|%d|%03d" % (pos['bar'], pos['beat'], pos['tick'])
        else:
            bbt = "-|-|-"
        seconds = int(pos['frame'] / pos['frame_rate'])
        (minutes, second) = divmod(seconds, 60)
        (hour, minute) = divmod(minutes, 60)
        time = "%d:%02d:%02d" % (hour, minute, second)
        self.bbtLabel.setText("%s\n%s" % (bbt, time))
        for line in self.btn_matrix:
            for btn in line:
                if btn.clip and btn.clip.audio_file:
                    value = ((btn.clip.last_offset
                              / self.song.length(btn.clip))
                             * 97)
                    btn.clip_position.setValue(value)
                    btn.clip_position.repaint()

    def updateDevices(self):
        for action in self.deviceGroup.actions():
            self.deviceGroup.removeAction(action)
            self.menuDevice.removeAction(action)
        for device in self.devices:
            action = QAction(device.name, self.menuDevice)
            action.setCheckable(True)
            action.setData(device)
            self.menuDevice.addAction(action)
            self.deviceGroup.addAction(action)
        action.setChecked(True)
        self.device = device

    def addDevice(self, device):
        self.devices.append(device)
        self.updateDevices()
        self.is_learn_device_mode = False

    def onDeviceSelect(self):
        self.device = self.deviceGroup.checkedAction().data()
        if self.device:
            if self.device.init_command:
                for note in self.device.init_command:
                    self.queue_out.put(note)
            self.redraw()

    def timebase_callback(self, state, nframes, pos, new_pos):
        if pos.frame_rate == 0:
            return None
        pos.valid = 0x10
        pos.bar_start_tick = BAR_START_TICK
        pos.beats_per_bar = self.beat_per_bar.value()
        pos.beat_type = BEAT_TYPE
        pos.ticks_per_beat = TICKS_PER_BEAT
        pos.beats_per_minute = self.bpm.value()
        ticks_per_second = (pos.beats_per_minute *
                            pos.ticks_per_beat) / 60
        ticks = (ticks_per_second * pos.frame) / pos.frame_rate
        (beats, pos.tick) = divmod(int(round(ticks, 0)),
                                   int(round(pos.ticks_per_beat, 0)))
        (bar, beat) = divmod(beats, int(round(pos.beats_per_bar, 0)))
        (pos.bar, pos.beat) = (bar + 1, beat + 1)
        return None
