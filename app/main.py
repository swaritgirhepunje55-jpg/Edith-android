"""
EDITH Android App - Created by Swarit Girhepunje
Runs FastAPI backend locally on Android
Shows EDITH UI in full-screen WebView
"""
import os, sys, threading, time, shutil, socket
from pathlib import Path

from kivy.utils import platform
IS_ANDROID = (platform == 'android')

from kivy.config import Config
Config.set('kivy', 'exit_on_escape', '0')

from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.graphics import Color, Rectangle, Ellipse
from kivy.clock import Clock
from kivy.metrics import dp

# ── Paths ─────────────────────────────────────────────────────────────
if IS_ANDROID:
    from android.storage import app_storage_path
    STORAGE = app_storage_path()
else:
    STORAGE = os.path.dirname(os.path.abspath(__file__))

ASSETS_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
BACKEND_DIR  = os.path.join(STORAGE, "backend")
FRONTEND_DIR = os.path.join(STORAGE, "frontend")
TMP_DIR      = os.path.join(STORAGE, "tmp")

# ── Safe temp paths ───────────────────────────────────────────────────
os.makedirs(TMP_DIR, exist_ok=True)
import tempfile
tempfile.tempdir = TMP_DIR
for k in ["TEMP","TMP","TMPDIR","HOME","USERPROFILE","APPDATA","LOCALAPPDATA"]:
    os.environ[k] = TMP_DIR

# ── Patch SSL ─────────────────────────────────────────────────────────
import ssl
_orig_ssl = ssl.create_default_context
def _safe_ssl(*a,**k):
    c=_orig_ssl(*a,**k); c.check_hostname=False; c.verify_mode=ssl.CERT_NONE; return c
ssl.create_default_context = _safe_ssl

# ── Setup: copy assets to writable storage ────────────────────────────
def setup_files():
    os.makedirs(BACKEND_DIR, exist_ok=True)
    os.makedirs(FRONTEND_DIR, exist_ok=True)
    for fn in ["main.py","requirements.txt",".env"]:
        src = os.path.join(ASSETS_DIR,"backend",fn)
        dst = os.path.join(BACKEND_DIR,fn)
        if os.path.exists(src):
            shutil.copy2(src,dst)
    for fn in os.listdir(os.path.join(ASSETS_DIR,"frontend")):
        shutil.copy2(
            os.path.join(ASSETS_DIR,"frontend",fn),
            os.path.join(FRONTEND_DIR,fn)
        )

# ── Start server ──────────────────────────────────────────────────────
_server_started = False
def start_server():
    global _server_started
    if _server_started: return
    _server_started = True
    sys.path.insert(0, BACKEND_DIR)
    os.chdir(BACKEND_DIR)
    try:
        import main as edith_main
        from pathlib import Path
        edith_main.FRONTEND_DIR = Path(FRONTEND_DIR)
        import uvicorn, asyncio
        config = uvicorn.Config(edith_main.app, host="127.0.0.1", port=8000,
                               log_level="error", loop="asyncio")
        server = uvicorn.Server(config)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())
    except Exception as e:
        print(f"[EDITH Server Error] {e}")

def wait_server(timeout=45):
    import urllib.request
    for _ in range(timeout):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health",timeout=1) as r:
                if r.status == 200: return True
        except: pass
    return False

# ── Android WebView ───────────────────────────────────────────────────
def launch_webview():
    if not IS_ANDROID:
        import webbrowser
        webbrowser.open("http://127.0.0.1:8000")
        return
    from jnius import autoclass
    from android.runnable import run_on_ui_thread
    WebView       = autoclass('android.webkit.WebView')
    WebViewClient = autoclass('android.webkit.WebViewClient')
    WebChromeClient = autoclass('android.webkit.WebChromeClient')
    LayoutParams  = autoclass('android.view.ViewGroup$LayoutParams')
    PythonActivity= autoclass('org.kivy.android.PythonActivity')
    View          = autoclass('android.view.View')

    @run_on_ui_thread
    def _build():
        activity = PythonActivity.mActivity
        wv = WebView(activity)
        s = wv.getSettings()
        s.setJavaScriptEnabled(True)
        s.setDomStorageEnabled(True)
        s.setMediaPlaybackRequiresUserGesture(False)
        s.setAllowFileAccess(True)
        s.setMixedContentMode(0)
        s.setBuiltInZoomControls(False)

        class MicClient(WebChromeClient):
            def onPermissionRequest(self, req):
                req.grant(req.getResources())
        wv.setWebChromeClient(MicClient())
        wv.setWebViewClient(WebViewClient())
        wv.loadUrl("http://127.0.0.1:8000")
        activity.addContentView(wv, LayoutParams(-1,-1))
        activity.getWindow().getDecorView().setVisibility(View.GONE)
    _build()

# ── Splash Screen ─────────────────────────────────────────────────────
class EDITHSplash(FloatLayout):
    def __init__(self,**kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(0.039,0.039,0.071,1)
            self._bg = Rectangle(pos=self.pos,size=self.size)
        self.bind(pos=self._upd,size=self._upd)
        with self.canvas:
            Color(0.784,0.314,0.961,0.2)
            self._orb = Ellipse(pos=(0,0),size=(280,280))
        self.bind(size=self._upd_orb)
        self._title = Label(text="EDITH",font_size=dp(50),bold=True,
            color=(0.784,0.314,0.961,1),
            pos_hint={"center_x":0.5,"center_y":0.72},
            size_hint=(1,None),height=dp(70))
        self.add_widget(self._title)
        self.add_widget(Label(text="Even Dead I'm The Hero",font_size=dp(13),
            color=(0.353,0.333,0.502,1),
            pos_hint={"center_x":0.5,"center_y":0.62},
            size_hint=(1,None),height=dp(25)))
        self._status = Label(text="Starting...",font_size=dp(13),
            color=(0.910,0.902,1.0,1),
            pos_hint={"center_x":0.5,"center_y":0.38},
            size_hint=(0.9,None),height=dp(25),halign="center")
        self.add_widget(self._status)
        self._bar = ProgressBar(max=100,value=0,
            pos_hint={"center_x":0.5,"center_y":0.32},
            size_hint=(0.8,None),height=dp(6))
        self.add_widget(self._bar)
        self.add_widget(Label(text="Created by Swarit Girhepunje | Class 11",
            font_size=dp(11),color=(0.227,0.208,0.333,1),
            pos_hint={"center_x":0.5,"center_y":0.12},
            size_hint=(1,None),height=dp(20)))

    def _upd(self,*a): self._bg.pos=self.pos; self._bg.size=self.size
    def _upd_orb(self,*a):
        cx,cy=self.width/2,self.height*0.55
        self._orb.pos=(cx-140,cy-140); self._orb.size=(280,280)

    def set_status(self,text,prog=None):
        def _do(dt):
            self._status.text=text
            if prog is not None: self._bar.value=prog
        Clock.schedule_once(_do,0)

# ── Main App ──────────────────────────────────────────────────────────
class EDITHApp(App):
    def build(self):
        self.title="EDITH"
        self.splash=EDITHSplash()
        return self.splash

    def on_start(self):
        if IS_ANDROID:
            from android.permissions import request_permissions,Permission
            request_permissions([
                Permission.INTERNET,Permission.RECORD_AUDIO,
                Permission.MODIFY_AUDIO_SETTINGS,
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WRITE_EXTERNAL_STORAGE,
            ])
        threading.Thread(target=self._boot,daemon=True).start()

    def _log(self,msg,prog=None):
        print(f"[EDITH] {msg}")
        self.splash.set_status(msg,prog)

    def _boot(self):
        try:
            self._log("Setting up EDITH...",10)
            setup_files()
            self._log("Starting server...",35)
            threading.Thread(target=start_server,daemon=True).start()
            self._log("Waiting for server...",60)
            wait_server(45)
            self._log("Opening EDITH!",90)
            time.sleep(0.3)
            Clock.schedule_once(lambda dt: launch_webview(),0)
        except Exception as e:
            self._log(f"Error: {str(e)[:50]}")
            import traceback; traceback.print_exc()

    def on_pause(self): return True
    def on_resume(self): pass

if __name__ == "__main__":
    EDITHApp().run()
