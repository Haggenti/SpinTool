from PyQt5.QtWidgets import QDialog, QFileDialog, QAbstractItemView
from superboucle.playlist_ui import Ui_Dialog
from superboucle.clip import verify_ext
#from superboucle.clip import load_song_from_file, verify_ext
import json
from os.path import basename, splitext

class PlaylistDialog(QDialog, Ui_Dialog):
    
    current_song_id = None
    
    def __init__(self, parent):
        super(PlaylistDialog, self).__init__(parent)
        self.gui = parent
        self.setupUi(self)
        self.updateList()
        self.removeSongBtn.clicked.connect(self.onRemove)
        self.addSongsBtn.clicked.connect(self.onAddSongs)
        self.loadPlaylistBtn.clicked.connect(self.onLoadPlaylist)
        self.savePlaylistBtn.clicked.connect(self.onSavePlaylist)
        self.loadSongBtn.clicked.connect(self.onLoadSong)
        self.playlistList.itemDoubleClicked.connect(self.onSongDoubleClick)
        self.playlistList.setDragDropMode(QAbstractItemView.InternalMove)
        self.playlistList.model().rowsMoved.connect(self.onMoveRows)
        
        self.geometry = self.gui.playlist_geometry
        
        if self.geometry:
            self.restoreGeometry(self.geometry)    
        
        if self.isVisible() == False:
            self.show()
        
    def updateList(self):
        self.playlistList.clear()
        for i, song in enumerate(self.gui.playlist):
            name, ext = splitext(basename(song))  # song.file_name
            self.playlistList.addItem('{}. {}'.format(i + 1, name))

    def onRemove(self):
        id = self.playlistList.currentRow()
        if id != -1:
            del self.gui.playlist[id]
            self.updateList()

    def onMoveRows(self, sourceParent, sourceStart, sourceEnd,
                   destinationParent, destinationRow):
        l = self.gui.playlist
        destinationRow -= destinationRow > sourceStart
        l.insert(destinationRow, l.pop(sourceStart))
        self.updateList()

    def onAddSongs(self):
        file_names, a = self.gui.getOpenFileName('Add Songs',
                                                 'SpinTool Song (*.sbs)',
                                                 self,
                                                 QFileDialog.getOpenFileNames)
        self.gui.playlist += file_names  # getSongs(file_names)
        self.updateList()

    def onLoadPlaylist(self):
        file_name, a = self.gui.getOpenFileName('Open Playlist',
                                                ('SpinTool '
                                                 'Playlist (*.sbp)'),
                                                self)
        if not file_name:
            return
        with open(file_name, 'r') as f:
            read_data = f.read()
        self.gui.playlist = json.loads(read_data)
        self.updateList()

    def onSavePlaylist(self):
        file_name, a = self.gui.getSaveFileName('Save Playlist',
                                                ('SpinTool '
                                                 'Playlist (*.sbp)'),
                                                self)

        if file_name:
            file_name = verify_ext(file_name, 'sbp')
            with open(file_name, 'w') as f:
                f.write(json.dumps(self.gui.playlist))

    def onLoadSong(self):
        id = self.playlistList.currentRow()
        self.loadSong(id)

    def onSongDoubleClick(self, item):
        id = self.playlistList.row(item)
        self.loadSong(id)

    def loadSong(self, id):
        if id == -1:
            return
        file_name = self.gui.playlist[id]
        try:
            self.gui.openSongFromDisk(file_name)
            # self.current_song_id = id
        except Exception as e:
            print("could not load File {}.\nError: {}".format(file_name, e))
    
       
    # saving window position
        
    def moveEvent(self, event):
        self.geometry = self.saveGeometry()
        self.gui.playlist_geometry = self.geometry
    
    def hideEvent(self, event):
        self.gui.actionPlaylist_Editor.setEnabled(True)
