"""AzureMusicPlayer — compact local MP3, WAV and FLAC player."""
import ctypes
import random
import sys
import io
import os
import unicodedata
from queue import Empty
from audio_formats import audio_info, SUPPORTED_EXTENSIONS
from audio_engine import AudioEngine
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, simpledialog, messagebox
from tkinter import ttk as native_ttk
import ttkbootstrap as ttk
from pathlib import Path
from PIL import Image, ImageDraw, ImageTk, ImageOps
from playlist_io import read_m3u, read_ttpl, write_ttpl
from player_state import load_state, save_state
from player_settings import load_volume, save_volume, load_window, save_window
from player_settings import load_playback, save_playback
from track_validation import TrackValidator
from windows_shell import reveal_file
from cover_art import read_cover, write_cover
from marquee import Marquee
from tkinterdnd2 import TkinterDnD, DND_FILES, COPY

NAVY = '#23364e'
LIGHT = '#eaf4ff'
BLUE = '#91c9f5'
DEFAULT_PLAYLIST = '預設清單'
ASSET_DIR = Path(__file__).resolve().parent / 'assets'


class AzureMusicPlayer(ttk.Window):
    def __init__(self, state_path=None, instance=None):
        super().__init__(themename='litera', title='AzureMusicPlayer', size=(410, 460),
                         resizable=(False, True))
        self.iconbitmap(str(ASSET_DIR / 'AzureMusicPlayer.ico'))
        self.app_icon = ImageTk.PhotoImage(file=str(ASSET_DIR / 'AzureMusicPlayer.png'), master=self)
        self.iconphoto(True, self.app_icon)
        with Image.open(ASSET_DIR / 'AzureMusicPlayer.png') as logo:
            self.default_cover = ImageTk.PhotoImage(
                logo.convert('RGBA').resize((124, 124), Image.Resampling.LANCZOS), master=self)
        self.minsize(410, 360)
        self.maxsize(410, self.winfo_screenheight())
        self.expanded_height = 460
        self.configure(bg=NAVY)
        self.instance = instance
        self.ipc_timer = None
        TkinterDnD.require(self)
        self.option_add('*Font', ('Microsoft JhengHei UI', 9))
        self.playing = False
        self.track_errors = {}
        self.playback_errors = {}
        self.track_signatures = {}
        self.validator = TrackValidator()
        self.audio = AudioEngine()
        self.current_row = None
        self.playing_playlist = None
        self.playing_tracks = []
        self.playing_index = 0
        self.dragging_progress = False
        self.play_mode = 'sequence'
        self.collapsed = False
        self.active_playlist = '預設清單'
        self.playlists = {'預設清單': [], '我的最愛': []}
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
        self.state_path = Path(state_path) if state_path else base / 'data' / 'playlists.json'
        self.settings_path = self.state_path.with_name('settings.json')
        self.play_mode, self.last_played = load_playback(self.settings_path)
        self.expanded_height, restore_collapsed = load_window(self.settings_path, self.winfo_screenheight() - 80)
        self.geometry(f'410x{self.expanded_height}')
        self.window_save_timer = None
        self.volume_percentage = load_volume(self.settings_path)
        self.volume_save_timer = None
        self.state_error = None
        try:
            stored = load_state(self.state_path)
            if stored:
                self.playlists, self.active_playlist = stored
        except Exception as exc:
            self.state_error = str(exc)
            self.after(200, lambda: messagebox.showerror('無法載入已儲存清單',
                       '原資料已保留，暫停自動儲存：' + self.state_error, parent=self))
        if DEFAULT_PLAYLIST not in self.playlists:
            self.playlists = {DEFAULT_PLAYLIST: [], **self.playlists}
        self.playlist_title = tk.StringVar(value='播放清單')
        self.title_text = tk.StringVar(value='請加入音樂')
        self.status = tk.StringVar(value='支援 MP3 / WAV / FLAC / M4A')
        style = self.style
        families = set(tkfont.families(self))
        self.song_font = next((name for name in ('Yu Gothic UI', 'Yu Gothic', 'MS Gothic')
                               if name in families), 'Microsoft JhengHei UI')
        style.configure('TButton', font=('Microsoft JhengHei UI', 9), padding=6)
        style.configure('Treeview', font=(self.song_font, 10), rowheight=30)
        style.configure('Treeview.Heading', font=('Microsoft JhengHei UI', 9, 'bold'))
        style.configure('TFrame', background=LIGHT)
        style.configure('TLabel', background=LIGHT, foreground='#234264')
        style.configure('Treeview', background=LIGHT, fieldbackground=LIGHT)
        style.layout('Treeview.Item', [('Treeitem.padding', {'sticky': 'nswe', 'children': [
            ('Treeitem.image', {'side': 'left', 'sticky': ''}),
            ('Treeitem.text', {'side': 'left', 'sticky': ''})]})])
        style.configure('primary.Horizontal.TScale', background=NAVY)
        style.configure('primary.Outline.TButton', background=LIGHT)
        self.icons = {name: self.make_icon(name) for name in
                      ('previous', 'play', 'pause', 'next', 'single', 'sequence', 'shuffle')}
        top = tk.Frame(self, bg=NAVY, padx=14, pady=12)
        top.pack(fill='x')
        self.cover = tk.Canvas(top, width=124, height=124, bg='#315374', highlightthickness=0)
        self.cover.grid(row=0, column=0, rowspan=4, padx=(0, 12), sticky='n')
        self.cover.create_image(62, 62, image=self.default_cover)
        self.cover_image = None
        self.cover_menu = tk.Menu(self, tearoff=False)
        self.cover_menu.add_command(label='更換封面並寫入歌曲', command=self.change_cover)
        self.cover_menu.add_command(label='重新讀取歌曲封面', command=self.load_track_cover)
        self.cover.bind('<Button-3>', self.show_cover_menu)
        self.title_marquee = Marquee(top, self.title_text, (self.song_font, 12, 'bold'),
                                    NAVY, 'white', width=190, height=28)
        self.title_marquee.grid(row=0, column=1, sticky='ew')
        self.time_text = tk.StringVar(value='00:00 / 00:00')
        tk.Label(top, textvariable=self.time_text, bg=NAVY, fg=BLUE,
                 font=('Segoe UI', 9)).grid(row=1, column=1, pady=(3, 0))
        self.progress = ttk.Scale(top, from_=0, to=100, length=190, bootstyle='primary')
        self.progress.grid(row=2, column=1, pady=(4, 6))
        self.progress.bind('<ButtonPress-1>', self.begin_seek)
        self.progress.bind('<ButtonRelease-1>', self.finish_seek)
        self.progress.bind('<KeyRelease>', self.finish_seek)
        controls = tk.Frame(top, bg=NAVY)
        controls.grid(row=3, column=1)
        self.control(controls, 'previous', lambda: self.change_track(-1))
        self.play_button = self.control(controls, 'play', self.toggle_play, large=True)
        self.control(controls, 'next', lambda: self.change_track(1))
        self.mode_button = self.control(controls, self.play_mode, self.cycle_mode)
        top.columnconfigure(1, weight=1)
        strip = tk.Frame(self, bg=NAVY, padx=14, pady=5)
        strip.pack(fill='x')
        tk.Label(strip, text='音量', bg=NAVY, fg=BLUE).pack(side='left')
        self.volume_text = tk.StringVar(value=f'{round(self.volume_percentage)}%')
        volume = ttk.Scale(strip, from_=0, to=100, length=100, bootstyle='primary',
                           command=self.set_volume)
        self.volume_slider = volume
        volume.set(self.volume_percentage)
        self.set_volume(self.volume_percentage)
        volume.pack(side='left', padx=8)
        tk.Label(strip, textvariable=self.volume_text, width=4, anchor='e',
                 bg=NAVY, fg=BLUE, font=('Segoe UI', 9)).pack(side='left')
        self.list_button = tk.Button(strip, text='收合清單', command=self.toggle_list,
                                     bg=NAVY, fg=BLUE, activebackground=NAVY,
                                     activeforeground='white', relief='flat', bd=0,
                                     highlightthickness=0, cursor='hand2')
        self.list_button.pack(side='right')
        self.playlist = ttk.Frame(self, padding=(10, 0, 10, 0))
        self.playlist.pack(fill='both', expand=True)
        header = ttk.Frame(self.playlist, padding=(4, 8))
        header.pack(fill='x')
        ttk.Label(header, textvariable=self.playlist_title, font=('Microsoft JhengHei UI', 10, 'bold')).pack(side='left')
        search = ttk.Frame(header)
        search.pack(side='left', fill='x', expand=True, padx=(12, 0))
        lens = Image.new('RGBA', (80, 80))
        lens_draw = ImageDraw.Draw(lens)
        lens_draw.ellipse((12, 10, 51, 49), outline='#416d98', width=7)
        lens_draw.line((47, 46, 67, 66), fill='#416d98', width=8)
        self.search_icon = ImageTk.PhotoImage(lens.resize((20, 20), Image.Resampling.LANCZOS))
        ttk.Label(search, image=self.search_icon).pack(side='left', padx=(0, 5))
        self.search_text = tk.StringVar()
        self.search_entry = ttk.Entry(search, textvariable=self.search_text)
        self.search_entry.pack(side='left', fill='x', expand=True)
        content = ttk.Frame(self.playlist)
        content.pack(fill='both', expand=True)
        sidebar = ttk.Frame(content, width=88)
        sidebar.pack(side='left', fill='y', padx=(0, 6))
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(0, weight=1)
        self.playlist_list = tk.Listbox(sidebar, bg='#dcecfb', fg='#234264',
                                        selectbackground='#639ed7', selectforeground='white',
                                        exportselection=False, bd=0, highlightthickness=0,
                                        activestyle='none', width=9, height=1,
                                        font=('Microsoft JhengHei UI', 11))
        self.playlist_list.grid(row=0, column=0, sticky='nsew')
        self.playlist_list.bind('<<ListboxSelect>>', self.switch_playlist)
        self.playlist_list.bind('<Double-1>', lambda _: self.rename_playlist())
        self.playlist_menu = tk.Menu(self, tearoff=False)
        self.playlist_menu.add_command(label='新增清單', command=self.new_playlist)
        self.playlist_menu.add_command(label='匯入 TTPL 清單', command=self.import_playlist)
        self.playlist_menu.add_command(label='匯出目前清單為 TTPL', command=self.export_playlist)
        self.playlist_menu.add_separator()
        self.playlist_menu.add_command(label='重新命名', command=self.rename_playlist)
        self.playlist_menu.add_command(label='刪除清單', command=self.delete_playlist)
        self.playlist_list.bind('<Button-3>', self.show_playlist_menu)
        table = ttk.Frame(content)
        table.pack(side='left', fill='both', expand=True)
        self.row_order = []
        self.tree = ttk.Treeview(table, columns=('number', 'name', 'duration', 'path'),
                                 displaycolumns=('number', 'name', 'duration'), show='tree headings',
                                 selectmode='extended', bootstyle='primary', height=5)
        self.tree.heading('number', text='#', anchor='center')
        self.tree.column('#0', width=20, minwidth=20, stretch=False)
        self.tree.heading('#0', text='')
        warning = Image.new('RGBA', (64, 64))
        warning_draw = ImageDraw.Draw(warning)
        warning_draw.rounded_rectangle((27, 5, 37, 40), radius=4, fill='#dc2626')
        warning_draw.ellipse((27, 47, 37, 57), fill='#dc2626')
        self.warning_icon = ImageTk.PhotoImage(warning.resize((16, 16), Image.Resampling.LANCZOS))
        self.tree.column('number', width=32, minwidth=30, anchor='center', stretch=False)
        self.tree.heading('name', text='歌曲名稱')
        self.tree.heading('duration', text='時間')
        self.tree.column('name', width=174, minwidth=80, anchor='w')
        self.tree.column('duration', width=52, minwidth=48, anchor='center', stretch=False)
        self.scroll_thumb_image = tk.PhotoImage(width=12, height=12)
        self.scroll_thumb_image.put('#9ca3af', to=(0, 0, 12, 12))
        style.element_create('Azure.Scrollbar.trough', 'from', 'clam', 'Vertical.Scrollbar.trough')
        style.element_create('Azure.Scrollbar.thumb', 'image', self.scroll_thumb_image,
                             border=0, sticky='nswe')
        style.layout('Azure.Vertical.TScrollbar', [('Azure.Scrollbar.trough', {
            'sticky': 'ns', 'children': [('Azure.Scrollbar.thumb', {'expand': 1, 'sticky': 'nswe'})]})])
        style.configure('Azure.Vertical.TScrollbar', troughcolor='#d9dce0', background='#d9dce0',
                        lightcolor='#d9dce0', darkcolor='#d9dce0', bordercolor='#d9dce0',
                        borderwidth=0, arrowsize=12)
        scroll = native_ttk.Scrollbar(table, command=self.tree.yview, style='Azure.Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=scroll.set)
        self.wheel_remainder = 0.0
        self.tree.bind('<MouseWheel>', self.scroll_tracks)
        scroll.bind('<MouseWheel>', self.scroll_tracks)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.tag_configure('alternate', background='#dcecfb')
        self.search_text.trace_add('write', lambda *_: self.apply_search())
        self.refresh_playlist_list()
        self.render_tracks()
        self.tree.bind('<Double-1>', lambda _: self.select_track())
        self.tree.bind('<Delete>', self.delete_selected_tracks)
        self.tree.bind('<<TreeviewSelect>>', self.preview_track_cover)
        self.tree.bind('<<TreeviewSelect>>', self.show_track_error, add='+')
        self.track_menu = tk.Menu(self, tearoff=False)
        self.track_menu.add_command(label='加入歌曲', command=self.add_files)
        self.track_menu.add_command(label='移除', command=self.remove)
        self.track_menu.add_command(label='打開檔案位置', command=self.open_file_location)
        self.track_menu.add_separator()
        self.track_menu.add_command(label='匯入 TTPL 清單', command=self.import_playlist)
        self.track_menu.add_command(label='匯出目前清單為 TTPL', command=self.export_playlist)
        self.tree.bind('<Button-3>', self.show_track_menu)
        self.drop_line = tk.Frame(self.tree, bg='#1769d2', height=3)
        self.drag_rows = ()
        self.drag_active = False
        self.drag_scroll = None
        self.tree.bind('<ButtonPress-1>', self.begin_track_drag)
        self.tree.bind('<B1-Motion>', self.move_track_drag)
        self.tree.bind('<ButtonRelease-1>', self.finish_track_drag)
        self.bind('<Escape>', lambda _: self.cancel_track_drag())
        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind('<<Drop>>', self.drop_files)
        self.status_label = tk.Label(self, textvariable=self.status, bg=NAVY,
                                     fg='#b9cde2', anchor='w', padx=10, pady=6,
                                     font=('Microsoft JhengHei UI', 8))
        self.status_label.pack(fill='x', side='bottom', before=self.playlist)
        self.bind('<space>', self.space_play)
        self.protocol('WM_DELETE_WINDOW', self.close_player)
        self.poll_timer = self.after(100, self.poll_audio)
        self.validation_timer = self.after(100, self.poll_track_validation)
        if restore_collapsed:
            self.collapsed = True
            self.playlist.pack_forget()
            self.minsize(410, 215)
            self.maxsize(410, 215)
            self.geometry('410x215')
            self.list_button.configure(text='顯示清單')
        self.bind('<Configure>', self.window_resized, add='+')
        self.restore_playback()
        if self.instance is not None:
            self.ipc_timer = self.after(100, self.poll_instance_requests)

    def restore_playback(self):
        if not self.last_played:
            return
        playlist, path = self.last_played['playlist'], self.last_played['path']
        # Match by file path, so inserted/reordered songs do not change the target.
        candidates = [playlist] if playlist in self.playlists else list(self.playlists)
        for name in candidates:
            for index, track in enumerate(self.playlists[name]):
                if os.path.normcase(track[2]) != os.path.normcase(path):
                    continue
                self.active_playlist = name
                self.refresh_playlist_list()
                self.render_tracks()
                row = self.all_track_rows()[index]
                self.current_row = row
                self.tree.selection_set(row)
                self.tree.focus(row)
                self.tree.see(row)
                self.title_text.set(track[0])
                self.load_track_cover()
                self.last_played = {'playlist': name, 'path': path}
                self.status.set('上次播放 · ' + self.mode_label() + ' · 按播放繼續')
                return

    def persist_playback(self):
        try:
            save_playback(self.settings_path, self.play_mode, self.last_played)
            return True
        except OSError as exc:
            self.status.set('無法儲存播放紀錄：' + str(exc))
            return False

    def poll_instance_requests(self):
        while True:
            try:
                paths = self.instance.requests.get_nowait()
            except Empty:
                break
            self.open_external_files(paths)
        self.ipc_timer = self.after(100, self.poll_instance_requests)

    def open_external_files(self, paths):
        self.deiconify()
        self.lift()
        if not paths:
            return
        paths = [str(Path(path).resolve()) for path in paths
                 if Path(path).suffix.lower() in SUPPORTED_EXTENSIONS]
        if not paths:
            self.status.set('不支援的音樂格式')
            return
        if not self.save_tracks():
            return
        self.active_playlist = DEFAULT_PLAYLIST
        self.search_text.set('')
        self.refresh_playlist_list()
        self.render_tracks()
        known = {os.path.normcase(track[2]) for track in self.playlists[DEFAULT_PLAYLIST]}
        new_paths = []
        for path in paths:
            if os.path.normcase(path) not in known:
                new_paths.append(path)
                known.add(os.path.normcase(path))
        if new_paths:
            self.add_paths(new_paths, insert_at=0)
        for row in self.all_track_rows():
            if os.path.normcase(self.tree.item(row, 'values')[3]) == os.path.normcase(paths[0]):
                self.play_row(row)
                break

    def window_resized(self, event):
        if event.widget is not self or self.state() != 'normal':
            return
        if not self.collapsed and event.height >= 360:
            self.expanded_height = event.height
        if self.window_save_timer is not None:
            self.after_cancel(self.window_save_timer)
        self.window_save_timer = self.after(300, self.persist_window)

    def persist_window(self):
        if self.window_save_timer is not None:
            self.after_cancel(self.window_save_timer)
        self.window_save_timer = None
        try:
            save_window(self.settings_path, self.expanded_height, self.collapsed)
            return True
        except OSError as exc:
            self.status.set('無法儲存視窗大小：' + str(exc))
            return False

    def refresh_track_warnings(self):
        for row in self.all_track_rows():
            path = self.tree.item(row, 'values')[3]
            error = self.playback_errors.get(path) or self.track_errors.get(path)
            self.tree.item(row, image=self.warning_icon if error else '')

    def show_track_error(self, event=None):
        selected = self.tree.selection()
        if selected:
            path = self.tree.item(selected[0], 'values')[3]
            error = self.playback_errors.get(path) or self.track_errors.get(path)
            if error:
                self.status.set(error)

    def poll_track_validation(self):
        try:
            results = self.validator.results.get_nowait()
        except Empty:
            results = {}
        for path, (signature, error) in results.items():
            if path in self.track_signatures and self.track_signatures[path] != signature:
                self.playback_errors.pop(path, None)
            self.track_signatures[path] = signature
            self.track_errors[path] = error
        self.refresh_track_warnings()
        self.validator.submit(track[2] for tracks in self.playlists.values() for track in tracks)
        self.validation_timer = self.after(1000, self.poll_track_validation)

    def make_icon(self, name):
        # Draw shapes rather than font glyphs so transport icons never become missing characters.
        scale = 4
        size = 40
        image = Image.new('RGBA', (size * scale, size * scale))
        draw = ImageDraw.Draw(image)
        color = BLUE
        def box(coords):
            return tuple(int(v * scale) for v in coords)
        def polygon(points):
            draw.polygon([(x * scale, y * scale) for x, y in points], fill=color)
        draw.ellipse(box((2, 2, 38, 38)),
                     outline='#739bc1', width=2 * scale)
        if name == 'play':
            polygon([(16, 11), (29, 20), (16, 29)])
        elif name == 'pause':
            for x in (14, 23):
                draw.rectangle(box((x, 12, x + 4, 28)), fill=color)
        elif name == 'previous':
            draw.rectangle(box((11, 12, 14, 28)), fill=color)
            polygon([(28, 12), (15, 20), (28, 28)])
        elif name == 'next':
            polygon([(12, 12), (25, 20), (12, 28)])
            draw.rectangle(box((26, 12, 29, 28)), fill=color)
        elif name == 'single':
            draw.arc(box((10, 10, 30, 30)), 35, 300, fill=color, width=2 * scale)
            polygon([(25, 8), (31, 13), (24, 16)])
            # The single-track marker is a drawn numeral, independent of fonts.
            draw.line([(18 * scale, 18 * scale), (21 * scale, 16 * scale),
                       (21 * scale, 25 * scale)], fill=color, width=2 * scale)
        elif name == 'sequence':
            for y in (13, 20, 27):
                draw.ellipse(box((10, y - 1, 12, y + 1)), fill=color)
                draw.line([(15 * scale, y * scale), (26 * scale, y * scale)],
                          fill=color, width=2 * scale)
            polygon([(25, 23), (30, 27), (25, 31)])
        elif name == 'shuffle':
            draw.line([tuple(v * scale for v in point) for point in
                       [(10, 13), (14, 13), (25, 27), (30, 27)]], fill=color, width=2 * scale)
            draw.line([tuple(v * scale for v in point) for point in
                       [(10, 27), (14, 27), (25, 13), (30, 13)]], fill=color, width=2 * scale)
            polygon([(26, 9), (31, 13), (26, 17)])
            polygon([(26, 23), (31, 27), (26, 31)])
        display_size = 56 if name in ('play', 'pause') else 48
        return ImageTk.PhotoImage(image.resize((display_size, display_size), Image.Resampling.LANCZOS))

    def show_cover_menu(self, event):
        state = 'normal' if self.cover_track_path() else 'disabled'
        self.cover_menu.entryconfigure(0, state=state)
        self.cover_menu.entryconfigure(1, state=state)
        try:
            self.cover_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.cover_menu.grab_release()

    def change_cover(self):
        target = self.cover_track_path()
        if not target:
            self.status.set('請先選擇歌曲')
            return
        path = filedialog.askopenfilename(parent=self, title='更換歌曲封面並寫入音樂檔',
                    filetypes=[('圖片', '*.png *.jpg *.jpeg *.webp *.bmp'), ('所有檔案', '*.*')])
        if not path:
            return
        resume = self.audio.file is not None
        position, paused = (self.audio.position, self.audio.paused) if resume else (0, False)
        if resume:
            self.audio.close()
        try:
            write_cover(target, path)
            self.load_track_cover()
            self.status.set('封面已寫入：' + Path(target).name)
        except Exception as exc:
            messagebox.showerror('無法寫入封面', str(exc), parent=self)
        finally:
            if resume:
                try:
                    self.audio.load(target)
                    self.audio.seek(position)
                    self.audio.paused = paused
                except Exception as exc:
                    self.stop()
                    self.status.set('無法恢復播放：' + str(exc))

    def cover_track_path(self):
        if self.audio.file and self.playing_tracks:
            return self.playing_tracks[self.playing_index][2]
        row = self.current_row if self.current_row in self.tree.get_children() else None
        if row is None:
            selected = self.tree.selection()
            row = selected[0] if selected else None
        return self.tree.item(row, 'values')[3] if row else None

    def scroll_tracks(self, event):
        # Six rows per Windows wheel notch; retain fine touchpad deltas.
        self.wheel_remainder += -event.delta * 6 / 120
        rows = int(self.wheel_remainder)
        if rows:
            self.wheel_remainder -= rows
            self.tree.yview_scroll(rows, 'units')
        return 'break'

    def preview_track_cover(self, event=None):
        if not self.audio.file:
            self.load_track_cover()

    def load_track_cover(self):
        self.reset_cover()
        target = self.cover_track_path()
        if not target:
            return
        try:
            data = read_cover(target)
            if data:
                with Image.open(io.BytesIO(data)) as image:
                    image = ImageOps.fit(ImageOps.exif_transpose(image).convert('RGB'), (124, 124),
                                         method=Image.Resampling.LANCZOS)
                    self.cover_image = ImageTk.PhotoImage(image)
                self.cover.delete('all')
                self.cover.create_image(62, 62, image=self.cover_image)
        except Exception:
            # Missing or malformed artwork must not prevent audio playback.
            pass

    def reset_cover(self):
        self.cover.delete('all')
        self.cover_image = None
        self.cover.create_image(62, 62, image=self.default_cover)

    def import_playlist(self):
        path = filedialog.askopenfilename(parent=self, title='匯入 TTPL 清單',
                    filetypes=[('TTPL 清單', '*.ttpl'), ('M3U 清單', '*.m3u *.m3u8')])
        if not path:
            return
        try:
            if Path(path).suffix.lower() == '.ttpl':
                title, tracks = read_ttpl(path)
            else:
                title, tracks = Path(path).stem, None
                paths = read_m3u(path)
        except Exception as exc:
            messagebox.showerror('無法匯入清單', str(exc), parent=self)
            return
        self.save_tracks()
        name = title
        base, number = name, 2
        while name in self.playlists:
            name = f'{base} ({number})'
            number += 1
        self.playlists[name] = tracks if tracks is not None else []
        self.active_playlist = name
        self.refresh_playlist_list()
        self.render_tracks()
        if tracks is None:
            self.add_paths(paths)
        else:
            missing = sum(not Path(track[2]).is_file() for track in tracks)
            self.status.set(f'已匯入 {len(tracks)} 首歌曲' + (f'（{missing} 首路徑不存在，仍保留於清單）' if missing else ''))

    def export_playlist(self):
        path = filedialog.asksaveasfilename(parent=self, title='匯出目前清單',
                    initialfile=self.active_playlist + '.ttpl', defaultextension='.ttpl',
                    filetypes=[('TTPL 清單', '*.ttpl')])
        if not path:
            return
        try:
            self.save_tracks()
            write_ttpl(path, self.active_playlist, self.playlists[self.active_playlist])
        except Exception as exc:
            messagebox.showerror('無法匯出清單', str(exc), parent=self)
            return
        self.status.set('已匯出清單：' + Path(path).name)

    def control(self, parent, name, command, large=False):
        button = tk.Button(parent, image=self.icons[name], command=command,
                           bg=NAVY, activebackground=NAVY, bd=0,
                           highlightthickness=0, relief='flat', overrelief='flat',
                           padx=2, pady=2, cursor='hand2')
        button.pack(side='left', padx=0)
        labels = {'previous': '上一首', 'play': '播放 / 暫停', 'next': '下一首'}
        button.bind('<Enter>', lambda _: self.status.set((self.mode_label() if name in ('single', 'sequence', 'shuffle') else labels[name])))
        return button

    @staticmethod
    def format_time(seconds):
        seconds = max(0, int(seconds))
        return f'{seconds // 60:02}:{seconds % 60:02}'

    def space_play(self, event):
        if not isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Scale)):
            self.toggle_play()
            return 'break'

    def toggle_play(self):
        if self.audio.file:
            self.playing = not self.playing
            self.audio.paused = not self.playing
            self.play_button.configure(image=self.icons['pause' if self.playing else 'play'])
            self.status.set('播放中' if self.playing else '已暫停')
            return
        rows = self.tree.get_children()
        if not rows:
            self.status.set('沒有符合搜尋的歌曲' if self.all_track_rows() else '請先加入音樂')
            return
        selected = self.tree.selection()
        row = selected[0] if selected else rows[0]
        if row != self.current_row or not self.audio.file:
            self.play_row(row)
            return
        self.playing = not self.playing
        self.audio.paused = not self.playing
        self.play_button.configure(image=self.icons['pause' if self.playing else 'play'])
        self.status.set('播放中' if self.playing else '已暫停')

    def play_row(self, row):
        self.save_tracks()
        self.playing_playlist = self.active_playlist
        self.playing_tracks = list(self.playlists[self.active_playlist])
        self.playing_index = self.all_track_rows().index(row)
        self.play_queued_track()

    def play_queued_track(self):
        name, duration, path = self.playing_tracks[self.playing_index]
        try:
            self.audio.load(path)
        except Exception as exc:
            self.playback_errors[path] = '無法播放：' + str(exc)
            self.refresh_track_warnings()
            self.stop()
            self.status.set('無法播放：' + str(exc))
            messagebox.showerror('無法播放音樂', str(exc), parent=self)
            return
        self.playback_errors.pop(path, None)
        self.track_errors.pop(path, None)
        self.refresh_track_warnings()
        rows = self.all_track_rows()
        self.current_row = rows[self.playing_index] if self.active_playlist == self.playing_playlist and self.playing_index < len(rows) else None
        self.load_track_cover()
        self.playing = True
        if self.current_row in self.tree.get_children():
            self.tree.selection_set(self.current_row)
            self.tree.see(self.current_row)
        self.title_text.set(name)
        self.play_button.configure(image=self.icons['pause'])
        self.status.set('播放中 · ' + Path(path).suffix.lstrip('.').upper())
        self.last_played = {'playlist': self.playing_playlist or self.active_playlist, 'path': path}
        self.persist_playback()

    def stop(self):
        self.audio.close()
        self.current_row = None
        self.playing_tracks = []
        self.playing_playlist = None
        self.playing = False
        self.play_button.configure(image=self.icons['play'])
        self.progress.set(0)
        self.time_text.set('00:00 / 00:00')

    def select_track(self):
        selected = self.tree.selection()
        if selected:
            self.play_row(selected[0])

    def change_track(self, delta):
        if self.playing_tracks and self.audio.file:
            indices = list(range(len(self.playing_tracks)))
            if self.play_mode == 'shuffle' and len(indices) > 1:
                indices.remove(self.playing_index)
                self.playing_index = random.choice(indices)
            else:
                self.playing_index = (self.playing_index + delta) % len(indices)
            self.play_queued_track()
            return
        rows = self.tree.get_children()
        if not rows:
            return
        selected = self.tree.selection()
        row = self.current_row if self.current_row in rows else (selected[0] if selected else rows[0])
        if self.play_mode == 'shuffle' and len(rows) > 1:
            target = random.choice([item for item in rows if item != row])
        else:
            target = rows[(rows.index(row) + delta) % len(rows)]
        self.play_row(target)

    def set_volume(self, value):
        percentage = max(0, min(100, float(value)))
        self.volume_percentage = percentage
        self.audio.volume = percentage / 200
        self.volume_text.set(f'{round(percentage)}%')
        if self.volume_save_timer is not None:
            self.after_cancel(self.volume_save_timer)
        self.volume_save_timer = self.after(300, self.persist_volume)

    def persist_volume(self):
        if self.volume_save_timer is not None:
            self.after_cancel(self.volume_save_timer)
        self.volume_save_timer = None
        try:
            save_volume(self.settings_path, self.volume_percentage)
            return True
        except OSError as exc:
            self.status.set('無法儲存音量：' + str(exc))
            return False

    def begin_seek(self, event=None):
        self.dragging_progress = True

    def finish_seek(self, event=None):
        self.audio.seek(float(self.progress.get()) / 100 * self.audio.duration)
        self.dragging_progress = False

    def poll_audio(self):
        if self.audio.file:
            duration = self.audio.duration
            position = min(self.audio.position, duration)
            self.time_text.set(f'{self.format_time(position)} / {self.format_time(duration)}')
            if not self.dragging_progress:
                self.progress.set(position / duration * 100 if duration else 0)
            if self.playing and self.audio.finished.is_set():
                error = self.audio.error
                if error:
                    if self.playing_tracks:
                        path = self.playing_tracks[self.playing_index][2]
                        self.playback_errors[path] = '播放中斷：' + error
                        self.refresh_track_warnings()
                    self.stop()
                    self.status.set('播放中斷：' + error)
                elif self.playing_tracks and self.play_mode == 'single':
                    self.play_queued_track()
                elif self.playing_tracks and self.play_mode == 'shuffle':
                    self.change_track(1)
                elif self.playing_tracks and self.playing_index < len(self.playing_tracks) - 1:
                    self.change_track(1)
                else:
                    self.stop()
                    self.status.set('清單播放完畢')
        self.poll_timer = self.after(100, self.poll_audio)

    def close_player(self):
        if not self.state_error and not self.save_tracks():
            return
        if not self.persist_playback():
            messagebox.showerror('無法儲存播放紀錄', self.status.get(), parent=self)
            return
        if not self.collapsed and self.state() == 'normal' and self.winfo_height() >= 360:
            self.expanded_height = self.winfo_height()
        if self.window_save_timer is not None:
            self.after_cancel(self.window_save_timer)
            self.window_save_timer = None
        if not self.persist_window():
            messagebox.showerror('無法儲存視窗大小', self.status.get(), parent=self)
            return
        if self.volume_save_timer is not None:
            self.after_cancel(self.volume_save_timer)
            self.volume_save_timer = None
        if not self.persist_volume():
            messagebox.showerror('無法儲存音量', self.status.get(), parent=self)
            return
        self.after_cancel(self.poll_timer)
        self.after_cancel(self.validation_timer)
        if self.ipc_timer is not None:
            self.after_cancel(self.ipc_timer)
        self.validator.stopped.set()
        self.cancel_track_drag()
        self.audio.close()
        self.destroy()

    def mode_label(self):
        return {'single': '單曲循環', 'sequence': '順序播放', 'shuffle': '隨機播放'}[self.play_mode]

    def cycle_mode(self):
        modes = ('single', 'sequence', 'shuffle')
        self.play_mode = modes[(modes.index(self.play_mode) + 1) % len(modes)]
        self.mode_button.configure(image=self.icons[self.play_mode])
        self.status.set(self.mode_label())
        self.persist_playback()

    def toggle_list(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.expanded_height = max(360, self.winfo_height())
            self.playlist.pack_forget()
            self.minsize(410, 215)
            self.maxsize(410, 215)
            self.geometry('410x215')
        else:
            self.playlist.pack(fill='both', expand=True)
            self.maxsize(410, self.winfo_screenheight())
            self.minsize(410, 360)
            self.geometry(f'410x{self.expanded_height}')
        self.list_button.configure(text='顯示清單' if self.collapsed else '收合清單')

    def save_tracks(self):
        self.playlists[self.active_playlist] = [tuple(self.tree.item(row, 'values')[1:])
                                                for row in self.all_track_rows()]
        if self.playing_playlist == self.active_playlist and self.current_row in self.all_track_rows():
            self.playing_tracks = list(self.playlists[self.active_playlist])
            self.playing_index = self.all_track_rows().index(self.current_row)
        return self.persist_playlists()

    def all_track_rows(self):
        self.row_order = [row for row in self.row_order if self.tree.exists(row)]
        known = set(self.row_order)
        self.row_order.extend(row for row in self.tree.get_children() if row not in known)
        return list(self.row_order)

    @staticmethod
    def matches_search(name, query):
        name = unicodedata.normalize('NFKC', name).casefold()
        tokens = unicodedata.normalize('NFKC', query).casefold().split()
        for token in tokens:
            characters = iter(name)
            if not all(any(character == wanted for character in characters) for wanted in token):
                return False
        return True

    def apply_search(self):
        if hasattr(self, 'drag_rows'):
            self.cancel_track_drag()
        query = self.search_text.get()
        selected = set(self.tree.selection())
        matches = []
        for row in self.all_track_rows():
            name = self.tree.item(row, 'values')[1]
            if self.matches_search(name, query):
                self.tree.move(row, '', 'end')
                matches.append(row)
            else:
                self.tree.detach(row)
        self.tree.selection_set([row for row in matches if row in selected])
        self.status.set(f'搜尋結果：{len(matches)} / {len(self.row_order)} 首' if query.strip()
                        else f'目前清單：{len(matches)} 首')

    def persist_playlists(self):
        if self.state_error:
            return False
        try:
            save_state(self.state_path, self.playlists, self.active_playlist)
            return True
        except Exception as exc:
            messagebox.showerror('無法儲存清單', str(exc), parent=self)
            return False

    def renumber_tracks(self):
        for number, row in enumerate(self.all_track_rows(), 1):
            values = self.tree.item(row, 'values')
            self.tree.item(row, values=(number, *values[1:]),
                           tags=('alternate',) if number % 2 == 0 else ())

    def render_tracks(self):
        self.current_row = None
        rows = self.all_track_rows()
        if rows:
            self.tree.delete(*rows)
        self.row_order = []
        for number, (name, duration, path) in enumerate(self.playlists[self.active_playlist], 1):
            row = self.tree.insert('', 'end', values=(number, name, duration, path),
                                   tags=('alternate',) if number % 2 == 0 else ())
            self.row_order.append(row)
        rows = self.tree.get_children()
        if rows:
            self.tree.selection_set(rows[0])
        if self.playing_playlist == self.active_playlist and self.playing_index < len(rows):
            self.current_row = rows[self.playing_index]
            self.tree.selection_set(self.current_row)
        self.refresh_track_warnings()
        self.apply_search()
        self.persist_playlists()

    def refresh_playlist_list(self):
        self.playlist_list.delete(0, 'end')
        for name in self.playlists:
            self.playlist_list.insert('end', name)
        index = list(self.playlists).index(self.active_playlist)
        self.playlist_list.selection_set(index)
        self.playlist_list.see(index)
        self.persist_playlists()

    def switch_playlist(self, event=None):
        selected = self.playlist_list.curselection()
        if not selected:
            return
        name = self.playlist_list.get(selected[0])
        if name == self.active_playlist:
            return
        self.save_tracks()
        self.active_playlist = name
        self.render_tracks()
        self.status.set('已切換清單：' + name)

    def new_playlist(self):
        name = simpledialog.askstring('新增播放清單', '清單名稱：', parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.playlists:
            messagebox.showinfo('播放清單', '已有相同名稱的清單。', parent=self)
            return
        self.save_tracks()
        self.playlists[name] = []
        self.active_playlist = name
        self.refresh_playlist_list()
        self.render_tracks()
        self.after_remove()

    def rename_playlist(self):
        if self.active_playlist == DEFAULT_PLAYLIST:
            self.status.set('預設清單不可重新命名')
            return
        name = simpledialog.askstring('重新命名', '清單名稱：',
                                      initialvalue=self.active_playlist, parent=self)
        if not name or not name.strip() or name.strip() == self.active_playlist:
            return
        name = name.strip()
        if name in self.playlists:
            messagebox.showinfo('播放清單', '已有相同名稱的清單。', parent=self)
            return
        self.save_tracks()
        if self.playing_playlist == self.active_playlist:
            self.playing_playlist = name
        if self.last_played and self.last_played['playlist'] == self.active_playlist:
            self.last_played['playlist'] = name
            self.persist_playback()
        self.playlists = {name if key == self.active_playlist else key: value
                          for key, value in self.playlists.items()}
        self.active_playlist = name
        self.refresh_playlist_list()

    def delete_playlist(self):
        if self.active_playlist == DEFAULT_PLAYLIST:
            self.status.set('預設清單不可刪除')
            return
        if len(self.playlists) == 1:
            self.status.set('至少保留一個播放清單')
            return
        if not messagebox.askyesno('刪除清單', f'確定要刪除「{self.active_playlist}」清單嗎？\n音樂檔案不會刪除。', parent=self):
            return
        if self.playing_playlist == self.active_playlist:
            self.playing_playlist = None
        del self.playlists[self.active_playlist]
        self.active_playlist = next(iter(self.playlists))
        self.refresh_playlist_list()
        self.render_tracks()
        self.after_remove()

    def show_playlist_menu(self, event):
        index = self.playlist_list.nearest(event.y)
        bounds = self.playlist_list.bbox(index) if index >= 0 else None
        on_item = bounds is not None and bounds[1] <= event.y < bounds[1] + bounds[3]
        if on_item:
            self.playlist_list.selection_clear(0, 'end')
            self.playlist_list.selection_set(index)
            self.switch_playlist()
        editable = on_item and self.active_playlist != DEFAULT_PLAYLIST
        self.playlist_menu.entryconfigure('重新命名', state='normal' if editable else 'disabled')
        self.playlist_menu.entryconfigure('刪除清單',
                                         state='normal' if editable and len(self.playlists) > 1 else 'disabled')
        try:
            self.playlist_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.playlist_menu.grab_release()

    def show_track_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.tree.focus(row)
        else:
            self.tree.selection_remove(*self.tree.selection())
        self.track_menu.entryconfigure('移除', state='normal' if self.tree.selection() else 'disabled')
        self.track_menu.entryconfigure('打開檔案位置', state='normal' if self.tree.selection() else 'disabled')
        try:
            self.track_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.track_menu.grab_release()

    def open_file_location(self):
        selected = self.tree.selection()
        if not selected:
            return
        row = self.tree.focus() if self.tree.focus() in selected else selected[0]
        path = self.tree.item(row, 'values')[3]
        try:
            if not path:
                raise FileNotFoundError('歌曲沒有檔案路徑')
            reveal_file(path)
        except OSError as exc:
            self.status.set('無法打開檔案位置：' + str(exc))
            messagebox.showerror('無法打開檔案位置', str(exc), parent=self)

    def add_files(self):
        paths = filedialog.askopenfilenames(title='加入音樂',
                    filetypes=[('音樂檔案', '*.mp3 *.wav *.flac *.m4a'), ('所有檔案', '*.*')])
        self.add_paths(paths)

    def drop_files(self, event):
        self.add_paths(self.tk.splitlist(event.data), insert_at=0)
        return COPY

    def add_paths(self, paths, insert_at=None):
        failures = []
        added = 0
        self.all_track_rows()
        for path in paths:
            try:
                if Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS:
                    raise ValueError('不支援的音樂格式')
                resolved = str(Path(path).resolve())
                try:
                    info = audio_info(path)
                    duration = self.format_time(info.duration)
                except Exception as exc:
                    duration = '--:--'
                    self.track_errors[resolved] = '無法讀取音樂：' + str(exc)
                row = self.tree.insert('', 'end', values=(0, Path(path).stem, duration, resolved))
                if insert_at is None:
                    self.row_order.append(row)
                else:
                    self.row_order.insert(insert_at + added, row)
                added += 1
            except Exception:
                failures.append(Path(path).name)
        if added:
            self.renumber_tracks()
            self.save_tracks()
            self.refresh_track_warnings()
            self.apply_search()
            if insert_at == 0:
                self.tree.yview_moveto(0)
        self.status.set(f'已加入 {added} 首音樂')
        if failures:
            messagebox.showwarning('部分檔案無法讀取', '\n'.join(failures[:10]), parent=self)

    def begin_track_drag(self, event):
        self.cancel_track_drag()
        row = self.tree.identify_row(event.y)
        if not row or self.tree.identify_region(event.x, event.y) not in ('cell', 'tree'):
            return
        self.tree.focus_set()
        self.drag_start = (event.x, event.y)
        selected = self.tree.selection()
        self.drag_rows = tuple(r for r in self.tree.get_children() if r in selected) if row in selected else (row,)
        # Preserve a selected group while the pointer is pressed for dragging.
        if row in selected and not event.state & 0x5:
            self.tree.focus(row)
            return 'break'

    def insertion_slot(self, y):
        rows = self.tree.get_children()
        slot, bottom = 0, 30
        for index, row in enumerate(rows):
            bounds = self.tree.bbox(row)
            if bounds and y < bounds[1] + bounds[3] / 2:
                return index, bounds[1]
            if bounds:
                slot, bottom = index + 1, bounds[1] + bounds[3]
        return slot, bottom

    def move_track_drag(self, event):
        if not self.drag_rows:
            return
        if not self.drag_active and max(abs(event.x - self.drag_start[0]), abs(event.y - self.drag_start[1])) < 5:
            return
        self.drag_active = True
        self.tree.selection_set(self.drag_rows)
        self.tree.configure(cursor='fleur')
        self.drag_pointer = (event.x, event.y)
        if self.drag_scroll is not None:
            self.after_cancel(self.drag_scroll)
        self.update_drag_hint()
        return 'break'

    def update_drag_hint(self):
        self.drag_scroll = None
        if not self.drag_active:
            return
        x, y = self.drag_pointer
        if not (0 <= x < self.tree.winfo_width() and 0 <= y < self.tree.winfo_height()):
            self.drop_line.place_forget()
            return
        if y < 45:
            self.tree.yview_scroll(-1, 'units')
        elif y > self.tree.winfo_height() - 25:
            self.tree.yview_scroll(1, 'units')
        self.tree.update_idletasks()
        slot, line_y = self.insertion_slot(y)
        self.drop_line.place(x=0, y=min(line_y, self.tree.winfo_height() - 3),
                             relwidth=1, height=3)
        self.drop_line.lift()
        self.status.set(f'放開移到第 {slot + 1} 個位置 · Esc 取消')
        self.drag_scroll = self.after(100, self.update_drag_hint)

    def finish_track_drag(self, event):
        active = self.drag_active
        if active and 0 <= event.x < self.tree.winfo_width() and 0 <= event.y < self.tree.winfo_height():
            rows = list(self.tree.get_children())
            slot, _ = self.insertion_slot(event.y)
            moving = set(self.drag_rows)
            offset = sum(row not in moving for row in rows[:slot])
            remaining = [row for row in rows if row not in moving]
            ordered = remaining[:offset] + list(self.drag_rows) + remaining[offset:]
            for index, row in enumerate(ordered):
                self.tree.move(row, '', index)
            visible = set(rows)
            reordered = iter(ordered)
            self.row_order = [next(reordered) if row in visible else row for row in self.all_track_rows()]
            self.renumber_tracks()
            self.save_tracks()
            self.status.set('已更新歌曲順序')
        self.cancel_track_drag()
        if active:
            return 'break'

    def cancel_track_drag(self):
        if self.drag_scroll is not None:
            self.after_cancel(self.drag_scroll)
            self.drag_scroll = None
        self.drag_rows = ()
        self.drag_active = False
        self.drop_line.place_forget()
        self.tree.configure(cursor='')

    def delete_selected_tracks(self, event=None):
        if self.tree.selection():
            self.remove()
        return 'break'

    def remove(self):
        if self.current_row in self.tree.selection():
            self.current_row = None
            self.playing_playlist = None
        for row in self.tree.selection():
            self.tree.delete(row)
        self.renumber_tracks()
        self.save_tracks()
        self.after_remove()

    def clear(self):
        rows = self.all_track_rows()
        if rows:
            self.tree.delete(*rows)
        self.save_tracks()
        self.after_remove()

    def after_remove(self):
        if not self.audio.file:
            self.title_text.set('請選擇歌曲')
        self.status.set('僅從清單移除，不會刪除檔案')


def main():
    from single_instance import SingleInstance
    from windows_identity import configure_process, configure_window
    configure_process()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    instance = SingleInstance()
    try:
        paths = [str(Path(path).expanduser().resolve()) for path in sys.argv[1:]]
        if not instance.is_primary:
            try:
                instance.forward(paths)
            except OSError as exc:
                messagebox.showerror('AzureMusicPlayer', str(exc))
            return
        app = AzureMusicPlayer(instance=instance)
        configure_window(app)
        if paths:
            app.after(100, lambda: app.open_external_files(paths))
        app.mainloop()
    finally:
        instance.close()


if __name__ == '__main__':
    main()
