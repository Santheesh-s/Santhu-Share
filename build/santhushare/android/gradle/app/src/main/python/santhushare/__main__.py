import os
import logging
import http.server
import socketserver
import threading
import shutil
import socket
import urllib.parse
import base64
import datetime
import time
from io import BytesIO

import segno
import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER, LEFT, RIGHT

# Chaquopy / Android specific imports
try:
    from java import jclass
    from android.app import NotificationChannel, NotificationManager
    from android.content import Context
    from android.os import Build
    from androidx.core.app import NotificationCompat, NotificationManagerCompat
    ANDROID_AVAILABLE = True
except ImportError:
    ANDROID_AVAILABLE = False

# Constants
PORT = 8080
# We will resolve the directory dynamically to handle permission grants at runtime
TARGET_UPLOAD_DIR = "/storage/emulated/0/SHARED_USING_SANTHUSHARE"

def get_real_upload_dir():
    try:
        logging.error(f"DEBUG: Checking access to {TARGET_UPLOAD_DIR}")
        if not os.path.exists(TARGET_UPLOAD_DIR):
            os.makedirs(TARGET_UPLOAD_DIR, exist_ok=True)
        # Test write
        tfile = os.path.join(TARGET_UPLOAD_DIR, '.test_write')
        with open(tfile, 'w') as f: f.write('ok')
        os.remove(tfile)
        logging.error(f"DEBUG: Write access confirmed for {TARGET_UPLOAD_DIR}")
        return TARGET_UPLOAD_DIR
    except Exception as e:
        logging.error(f"DEBUG: Failed to write to target dir: {e}")
        # Fallback to internal storage
        internal = os.path.join(os.path.dirname(__file__), "uploads")
        if not os.path.exists(internal):
            os.makedirs(internal, exist_ok=True)
        logging.error(f"DEBUG: Falling back to internal storage: {internal}")
        return internal


LOG_DIR = "/storage/emulated/0/santhu_logs"

def ensure_log_dir():
    try:
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR, exist_ok=True)
        logging.error(f"DEBUG: Log dir ready: {LOG_DIR}")
    except Exception as e:
        logging.error(f"DEBUG: Failed to create log dir {LOG_DIR}: {e}")

ALLOWED_ROOTS = [
    "/storage/emulated/0",
    "/sdcard",
    "/storage",
    os.path.dirname(__file__),
]


# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- History / Notification System ---
class AppManager:
    _instance = None
    
    def __init__(self, app_ref):
        AppManager._instance = self
        self.app = app_ref
        self.history = [] # List of dicts
        
    @classmethod
    def get(cls):
        return cls._instance

    def add_history(self, title, subtitle, icon=None):
        item = {"title": title, "subtitle": subtitle, "icon": icon}
        self.history.insert(0, item)
        # Verify if running on UI thread or schedule
        if hasattr(self.app, 'loop'):
            self.app.loop.call_soon_threadsafe(self.app.update_history_ui)
    
    def update_progress(self, value):
        # Value 0 to 100
        def _update():
            if hasattr(self.app, 'progress_bar'):
                self.app.progress_bar.value = value
        # Toga thread safety
        if hasattr(self.app, 'main_window'):
            self.app.loop.call_soon_threadsafe(_update)
        
    def send_notification(self, title, content):
        if not ANDROID_AVAILABLE:
            print(f"NOTIFICATION: {title} - {content}")
            return

        try:
            context = self.app._impl.native.getApplicationContext()
            channel_id = "santhushare_channel"
            
            if Build.VERSION.SDK_INT >= Build.VERSION_CODES.O:
                name = "File Transfer"
                description_text = "Notifications for file transfers"
                importance = NotificationManager.IMPORTANCE_DEFAULT
                channel = NotificationChannel(channel_id, name, importance)
                channel.setDescription(description_text)
                notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE)
                notificationManager.createNotificationChannel(channel)

            builder = NotificationCompat.Builder(context, channel_id) \
                .setSmallIcon(17301633) \
                .setContentTitle(title) \
                .setContentText(content) \
                .setPriority(NotificationCompat.PRIORITY_DEFAULT) \
                .setAutoCancel(True)

            notificationManager = NotificationManagerCompat.from_(context)
            # notificationId is a unique int for each notification that you must define
            notificationManager.notify(int(time.time()), builder.build())
        except Exception as e:
            logging.error(f"Failed to send notification: {e}")

# --- HTML / JS Resources ---
CSS_VARS = """
:root {
    --bg: #ffffff; --text: #000000; --card: #f5f5f5; --accent: #6200ee; --border: #ddd;
}
[data-theme="dark"] {
    --bg: #121212; --text: #e0e0e0; --card: #1e1e1e; --accent: #bb86fc; --border: #333;
}
body { background: var(--bg); color: var(--text); font-family: sans-serif; transition: background 0.3s, color 0.3s; padding: 20px; max-width: 800px; margin: 0 auto; }
.card { background: var(--card); padding: 20px; border-radius: 12px; margin-bottom: 20px; border: 1px solid var(--border); }
a { color: var(--accent); text-decoration: none; font-weight: bold; }
ul { list-style: none; padding: 0; }
li { padding: 12px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
button, input[type="submit"], .btn { background: var(--accent); color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-size: 1rem; }
input[type="file"] { width: 100%; margin: 10px 0; }
.header-row { display: flex; justify-content: space-between; align-items: center; }
progress { width: 100%; height: 20px; margin-top: 10px; }
"""

GAME_SCRIPT = """
var canvas, ctx, grid=16, snake={x:160,y:160,dx:16,dy:0,cells:[],max:4}, apple={x:320,y:320}, score=0;
function loop() {
    requestAnimationFrame(loop);
    if (++count < 6) return; count=0;
    ctx.clearRect(0,0,canvas.width,canvas.height);
    snake.x+=snake.dx; snake.y+=snake.dy;
    if(snake.x<0) snake.x=canvas.width-grid; if(snake.x>=canvas.width) snake.x=0;
    if(snake.y<0) snake.y=canvas.height-grid; if(snake.y>=canvas.height) snake.y=0;
    snake.cells.unshift({x:snake.x,y:snake.y});
    if(snake.cells.length>snake.max) snake.cells.pop();
    
    ctx.fillStyle='red'; ctx.fillRect(apple.x,apple.y,grid-1,grid-1);
    ctx.fillStyle='#bb86fc';
    snake.cells.forEach((c,i)=>{
        ctx.fillRect(c.x,c.y,grid-1,grid-1);
        if(c.x===apple.x && c.y===apple.y){
            snake.max++; score+=10; document.getElementById('score').innerText=score;
            apple.x=Math.floor(Math.random()*25)*grid; apple.y=Math.floor(Math.random()*25)*grid;
        }
        for(var j=i+1;j<snake.cells.length;j++){
             if(c.x===snake.cells[j].x && c.y===snake.cells[j].y){
                 snake.x=160;snake.y=160;snake.cells=[];snake.max=4;score=0;document.getElementById('score').innerText=0;
             }
        }
    });
}
var count=0;
function initGame(){
   canvas=document.getElementById('game'); ctx=canvas.getContext('2d');
   document.addEventListener('keydown',e=>{
       if(e.which===37 && snake.dx===0){snake.dx=-grid;snake.dy=0}
       else if(e.which===38 && snake.dy===0){snake.dy=-grid;snake.dx=0}
       else if(e.which===39 && snake.dx===0){snake.dx=grid;snake.dy=0}
       else if(e.which===40 && snake.dy===0){snake.dy=grid;snake.dx=0}
   });
   // Touch
   let sx=0,sy=0;
   canvas.addEventListener('touchstart',e=>{sx=e.touches[0].clientX;sy=e.touches[0].clientY}, {passive:false});
   canvas.addEventListener('touchmove',e=>{e.preventDefault();}, {passive:false});
   canvas.addEventListener('touchend',e=>{
       let ex=e.changedTouches[0].clientX, ey=e.changedTouches[0].clientY;
       let dx=ex-sx, dy=ey-sy;
       if(Math.abs(dx)>Math.abs(dy)){
           if(dx>0 && snake.dx===0){snake.dx=grid;snake.dy=0}
           else if(dx<0 && snake.dx===0){snake.dx=-grid;snake.dy=0}
       }else{
           if(dy>0 && snake.dy===0){snake.dy=grid;snake.dx=0}
           else if(dy<0 && snake.dy===0){snake.dy=-grid;snake.dx=0}
       }
   });
   loop();
}
"""

HTML_LAYOUT = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SanthuShare</title>
<style>{CSS_VARS}</style>
<script>
function toggleTheme() {{
    const b = document.body;
    const current = b.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    b.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
}}
window.onload = function() {{
    const t = localStorage.getItem('theme') || 'dark';
    document.body.setAttribute('data-theme', t);
    // Init game if present
    if(document.getElementById('game')) initGame();
}}
</script>
</head>
<body>
<div class="header-row">
    <h2>SanthuShare</h2>
    <button onclick="toggleTheme()">🌗 Theme</button>
</div>

<div class="card">
    <h3>📤 Fast Upload</h3>
    <form id="upload-form" action="/" method="post" enctype="multipart/form-data">
        <input type="file" name="file" multiple>
        <input type="submit" value="Transfer Files">
    </form>
    <div id="progress_box" style="display:none">
        <progress id="pb" max="100" value="0"></progress>
        <span id="pct">0%</span>
    </div>
</div>

<div class="card">
    <h3>📁 Files & Storage</h3>
    <div><a href="/browse?path=/storage/emulated/0">Browse Internal Storage</a></div>
</div>

<div class="card">
    <h3>🎮 Waiting Room</h3>
    <p>Score: <span id="score">0</span></p>
    <canvas id="game" width="400" height="400" style="background:#000;width:100%;max-width:400px;display:block;margin:auto;border:2px solid var(--accent)"></canvas>
    <script>{GAME_SCRIPT}</script>
</div>

<script>
var form = document.getElementById('upload-form');
var pbox = document.getElementById('progress_box');
var pb = document.getElementById('pb');
var pct = document.getElementById('pct');

form.addEventListener('submit', function(e) {{
    e.preventDefault();
    var fileInput = form.querySelector('input[type="file"]');
    if (fileInput.files.length === 0) {{
        alert("Please select files before transferring.");
        return;
    }}
    var fd = new FormData(form);
    var xhr = new XMLHttpRequest();
    xhr.upload.onprogress = function(e) {{
        if(e.lengthComputable) {{
            var p = (e.loaded/e.total)*100;
            pb.value = p;
            pct.innerText = p.toFixed(0) + '%';
            pbox.style.display='block';
        }}
    }};
    xhr.onload = function() {{
        pbox.style.display='none';
        if(xhr.status===200) alert('Transfer Complete!');
        else alert('Error: '+xhr.responseText);
    }};
    xhr.open('POST', '/');
    xhr.send(fd);
}});
</script>
</body></html>
"""

# --- HTTP Handler ---
import zipfile
try:
    import cgi
except Exception:
    cgi = None
import re

def parse_multipart_rfile(fp, headers):
    try:
        content_type = headers.get('Content-Type', '')
        logging.error(f"DEBUG: CT: {content_type}")
        
        if 'multipart/form-data' not in content_type:
            logging.error("DEBUG: Not multipart")
            return {}
            
        boundary_match = re.search(r'boundary=([^;]+)', content_type)
        if not boundary_match:
            boundary_match = re.search(r'boundary=(.+)', content_type)
        
        if not boundary_match:
            logging.error("DEBUG: No boundary found")
            return {}
            
        boundary = boundary_match.group(1).strip('"')
        logging.error(f"DEBUG: Boundary: {boundary}")
        
        boundary_bytes = b'--' + boundary.encode()
        
        try:
            cl = int(headers.get('Content-Length', 0))
        except:
            cl = 0
            
        logging.error(f"DEBUG: CL: {cl}")
        if cl == 0: return {}

        body = fp.read(cl)
        logging.error(f"DEBUG: Read {len(body)} bytes")
        
        parts = body.split(boundary_bytes)
        logging.error(f"DEBUG: Split into {len(parts)} parts")
        
        result = {}
        
        class Part:
            def __init__(self, filename=None, data=b'', value=None): 
                self.filename = filename 
                self.file = BytesIO(data) 
                self.value = value

        for i, part in enumerate(parts):
            if not part or part == b'--' or part == b'--\r\n' or part == b'--\n':
                continue
            
            # Clean up leading CRLF/LF
            if part.startswith(b'\r\n'): part = part[2:]
            elif part.startswith(b'\n'): part = part[1:]
            
            if part.endswith(b'\r\n'): part = part[:-2]
            elif part.endswith(b'\n'): part = part[:-1]
            if part.endswith(b'--'): part = part[:-2] # End of body
            
            try:
                if b'\r\n\r\n' in part:
                    header_bytes, content_bytes = part.split(b'\r\n\r\n', 1)
                elif b'\n\n' in part:
                    header_bytes, content_bytes = part.split(b'\n\n', 1)
                else:
                    continue
            except Exception as e:
                logging.error(f"DEBUG: Part split error: {e}")
                continue

            headers_text = header_bytes.decode('utf-8', errors='ignore')
            name = None
            filename = None
            
            for line in headers_text.splitlines():
                if 'content-disposition' in line.lower():
                    m_name = re.search(r'name="([^"]+)"', line)
                    if m_name: name = m_name.group(1)
                    m_filename = re.search(r'filename="([^"]*)"', line)
                    if m_filename: filename = m_filename.group(1)

            if not name:
                continue
                
            logging.error(f"DEBUG: Found part name={name} filename={filename}")

            if filename:
                p = Part(filename=os.path.basename(filename), data=content_bytes)
            else:
                p = Part(value=content_bytes.decode('utf-8', errors='ignore'))
            
            if name in result:
                if isinstance(result[name], list): result[name].append(p)
                else: result[name] = [result[name], p]
            else: result[name] = p
                
        return result
    except Exception as e:
        logging.error(f"DEBUG: Parser Exception: {e}")
        return {}

class SecureHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    
    def check_auth(self):
        if not self.server.password: return True
        auth = self.headers.get('Authorization')
        if not auth: 
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="SanthuShare"')
            self.end_headers()
            self.wfile.write(b"Auth Required")
            return False
        try:
            m, c = auth.split()
            if m.lower()!='basic': raise
            d = base64.b64decode(c).decode().split(':', 1)
            if d[1] != self.server.password: raise
        except:
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="SanthuShare"')
            self.end_headers()
            self.wfile.write(b"Access Denied")
            return False
        return True

    def do_GET(self):
        if not self.check_auth(): return
        
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_LAYOUT.encode('utf-8'))
            return
            
        if parsed.path == '/browse':
            qs = urllib.parse.parse_qs(parsed.query)
            path = qs.get('path', ["/storage/emulated/0"])[0]
            if not os.path.exists(path): path = get_real_upload_dir()
            
            try:
                items = sorted(os.listdir(path))
            except Exception as e:
                self.send_error(500, str(e))
                return

            html = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{CSS_VARS}</style><script>function toggleTheme(){{var b=document.body;b.setAttribute('data-theme',b.getAttribute('data-theme')==='dark'?'light':'dark')}}window.onload=function(){{document.body.setAttribute('data-theme',localStorage.getItem('theme')||'dark')}}</script></head><body>"]
            html.append(f"<div class='card'><h3>📂 {os.path.basename(path) or 'Root'}</h3>")
            parent = os.path.dirname(path)
            if parent != path:
                html.append(f"<a href='/browse?path={urllib.parse.quote(parent)}'>⬅️ Up Level</a><hr>")
            
            html.append("<ul>")
            for item in items:
                full = os.path.join(path, item)
                q = urllib.parse.quote(full)
                if os.path.isdir(full):
                    html.append(f"<li><span>📁 {item}</span><span><a href='/browse?path={q}'>Open</a> | <a href='/zip?path={q}'>Zip</a></span></li>")
                else:
                    sz = "0B"
                    try: sz = f"{os.path.getsize(full)/1024:.1f} KB" 
                    except: pass
                    html.append(f"<li><span>📄 {item} <small>({sz})</small></span><a href='/download?path={q}'>Download</a></li>")
            html.append("</ul></div><div class='card'>Current Upload Dir: "+get_real_upload_dir()+"</div><button onclick='toggleTheme()'>Theme</button></body></html>")
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write("".join(html).encode('utf-8'))
            return

        if parsed.path == '/download' or parsed.path == '/zip':
            qs = urllib.parse.parse_qs(parsed.query)
            path = qs.get('path', [None])[0]
            if not path or not os.path.exists(path):
                self.send_error(404)
                return
            
            if parsed.path == '/zip' and os.path.isdir(path):
                name = os.path.basename(path) + ".zip"
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', f'attachment; filename="{name}"')
                self.end_headers()
                
                with zipfile.ZipFile(self.wfile, 'w', zipfile.ZIP_DEFLATED) as z:
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            fn = os.path.join(root, file)
                            arcname = os.path.relpath(fn, os.path.dirname(path))
                            z.write(fn, arcname)
                
                AppManager.get().add_history("Zipped Folder", f"Served {name}")
                return

            try:
                sz = os.path.getsize(path)
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(path)}"')
                self.send_header('Content-Length', str(sz))
                self.end_headers()
                with open(path, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile)
                
                AppManager.get().add_history("File Sent", os.path.basename(path))
            except Exception as e:
                pass
            return

    def do_POST(self):
        if not self.check_auth(): return
        
        try:
            logging.error("DEBUG: Starting POST request")
            ct = self.headers.get('Content-Type')
            files = []
            
            if cgi:
                env = {'REQUEST_METHOD':'POST', 'CONTENT_TYPE':ct}
                fs = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)
                if 'file' in fs:
                    fl = fs['file']
                    files = fl if isinstance(fl, list) else [fl]
            else:
                 res = parse_multipart_rfile(self.rfile, self.headers)
                 if 'file' in res:
                     files = res['file'] if isinstance(res['file'], list) else [res['file']]
            
            logging.error(f"DEBUG: Found {len(files)} files to process")
            count = 0
            total_files = len(files)
            for i, item in enumerate(files):
                pct = int(((i) / total_files) * 50)
                AppManager.get().update_progress(pct)
                
                fname = getattr(item, 'filename', None)
                if not fname: 
                    logging.error("DEBUG: Skipped item with no filename")
                    continue
                fname = os.path.basename(fname)
                
                # Determine destination
                target_dir = get_real_upload_dir()
                dest = os.path.join(target_dir, fname)
                logging.error(f"DEBUG: Attempting to write file to: {dest}")
                
                try:
                    with open(dest, 'wb') as f:
                        if hasattr(item, 'file'):
                            item.file.seek(0)
                            # Optimised large file copy
                            fsrc = item.file
                            fdst = f
                            length = 1024*1024 # 1MB buffer
                            copied = 0
                            while True:
                                buf = fsrc.read(length)
                                if not buf:
                                    break
                                fdst.write(buf)
                                copied += len(buf)
                            logging.error(f"DEBUG: Streamed {copied} bytes to {dest}")
                        else:
                            content = item.value if isinstance(item.value, bytes) else item.value.encode()
                            f.write(content)
                            logging.error(f"DEBUG: Wrote {len(content)} bytes to {dest}")
                except Exception as e:
                    logging.error(f"DEBUG: FAILED to write file {dest}: {e}")
                    raise e
                
                count += 1
                AppManager.get().update_progress(int(((i+1)/total_files)*100))
                AppManager.get().add_history("File Received", fname)
                AppManager.get().send_notification("New File Received", f"{fname}")
            
            AppManager.get().update_progress(0) # Reset

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Success")
        except Exception as e:
            logging.error(f"DEBUG: POST Error: {e}")
            self.send_error(500, str(e))

class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        print("Initializing ReusableTCPServer with reuse_address=True")
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)

class ServerThread(threading.Thread):
    def __init__(self, port, pwd):
        super().__init__(daemon=True)
        self.port = port
        self.pwd = pwd
        self.httpd = None
    
    def run(self):
        import time
        retries = 10
        while retries > 0:
            try:
                self.httpd = ReusableTCPServer(('0.0.0.0', self.port), SecureHandler)
                self.httpd.password = self.pwd
                print(f"Server started on port {self.port}")
                self.httpd.serve_forever()
                break
            except OSError as e:
                if e.errno == 98: # Address already in use
                    print(f"Port {self.port} in use, retrying in 1s... ({retries} left)")
                    retries -= 1
                    time.sleep(1)
                else:
                    logging.error(f"Server Error: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    break
            except Exception as e:
                logging.error(f"Server Error: {str(e)}")
                import traceback
                traceback.print_exc()
                break
    
    def stop(self):
        if self.httpd: 
            self.httpd.shutdown()
            self.httpd.server_close()

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(('10.255.255.255', 1)); return s.getsockname()[0]
    except: return '127.0.0.1'
    finally: s.close()

class SanthuShare(toga.App):
    def startup(self):
        logging.error("DEBUG: App Startup Begin")
        AppManager(self)
        self.request_android_permissions()
        
        # Attempt to create directories at startup
        get_real_upload_dir()
        ensure_log_dir()
        
        self.main_window = toga.MainWindow(title=self.formal_name)

        
        box_style = Pack(direction=COLUMN, padding=10, background_color='#f0f0f0') 
        
        self.status = toga.Label("Server Offline", style=Pack(font_weight='bold', font_size=14, color='red', padding=5))
        self.qr_view = toga.ImageView(style=Pack(width=200, height=200, align_items=CENTER, padding=10))
        self.pwd_input = toga.TextInput(placeholder="Enter Secure Password", style=Pack(padding=5))
        
        btn_box = toga.Box(style=Pack(direction=ROW, padding=5))
        self.start_btn = toga.Button("Start Server", on_press=self.on_start, style=Pack(flex=1))
        self.stop_btn = toga.Button("Stop Server", on_press=self.on_stop, enabled=False, style=Pack(flex=1))
        btn_box.add(self.start_btn)
        btn_box.add(self.stop_btn)
        
        self.progress_bar = toga.ProgressBar(max=100, value=0, style=Pack(padding_top=10, padding_bottom=10))

        theme_box = toga.Box(style=Pack(direction=ROW, padding=5))
        theme_spacer = toga.Box(style=Pack(flex=1))
        self.theme_switch = toga.Switch("Dark Mode", on_change=self.on_theme_change)
        theme_box.add(theme_spacer)
        theme_box.add(self.theme_switch)

        self.history_list = toga.DetailedList(
            data=[],
            style=Pack(flex=1, padding=5)
        )
        
        container = toga.Box(style=box_style)
        container.add(theme_box)
        container.add(self.status)
        container.add(self.qr_view)
        container.add(self.pwd_input)
        container.add(btn_box)
        container.add(self.progress_bar)
        container.add(toga.Label("History", style=Pack(padding=5, font_weight='bold')))
        container.add(self.history_list)
        
        self.main_window.content = container
        self.main_window.show()
        
        self.server_thread = None

    def on_theme_change(self, widget):
        bg = '#121212' if widget.value else '#f0f0f0'
        try:
             self.main_window.content.style.background_color = bg
        except:
             pass

    def on_start(self, widget):
        pwd = self.pwd_input.value
        if not pwd:
            self.main_window.info_dialog("Security Alert", "A password is MANDATORY for security.")
            return
            
        self.server_thread = ServerThread(PORT, pwd)
        self.server_thread.start()
        
        ip = get_ip()
        url = f"http://{ip}:{PORT}/"
        
        self.status.text = f"RUNNING: {url}"
        self.status.style.color = 'green'
        
        qr = segno.make(url)
        bio = BytesIO()
        qr.save(bio, kind='png', scale=5, dark="#6200ee", light="#ffffff")
        bio.seek(0)
        self.qr_view.image = toga.Image(src=bio.read())
        
        self.start_btn.enabled = False
        self.stop_btn.enabled = True
        self.pwd_input.readonly = True
        
        AppManager.get().add_history("Server Started", f"Listening on {PORT}")

    def on_stop(self, widget):
        if self.server_thread:
            self.server_thread.stop()
        self.status.text = "OFFLINE"
        self.status.style.color = 'red'
        self.qr_view.image = None
        self.start_btn.enabled = True
        self.stop_btn.enabled = False
        self.pwd_input.readonly = False
        AppManager.get().add_history("Server Stopped", "Manual Stop")

    def update_history_ui(self):
        current_hist = AppManager.get().history
        self.history_list.data = current_hist

    def request_android_permissions(self):
        if not ANDROID_AVAILABLE: return
        try:
            # 1. Try getting Activity from Toga (most reliable in this context)
            activity = getattr(self._impl, "native", None)
            
            from java import jclass
            if not activity:
                # 2. Fallback to Chaquopy lookup if Toga native is not yet set
                Python = jclass("com.chaquo.python.Python")
                activity = Python.getPlatform().getActivity()

            PackageManager = jclass("android.content.pm.PackageManager")
            ActivityCompat = jclass("androidx.core.app.ActivityCompat")
            ContextCompat = jclass("androidx.core.content.ContextCompat")
            Build = jclass("android.os.Build") # Ensure we use the Java Build class for SDK_INT check if needed, or python's if imported
            Environment = jclass("android.os.Environment")
            Intent = jclass("android.content.Intent")
            Settings = jclass("android.provider.Settings")
            Uri = jclass("android.net.Uri")
            Manifest = jclass("android.Manifest")

            logging.info(f"Android SDK: {Build.VERSION.SDK_INT}")

            # 1. SPECIAL: Manage All Files Access (Android 11 / SDK 30+)
            if Build.VERSION.SDK_INT >= 30:
                is_manager = Environment.isExternalStorageManager()
                logging.info(f"isExternalStorageManager: {is_manager}")
                if not is_manager:
                    logging.info("Requesting MANAGE_EXTERNAL_STORAGE permission (Intent)")
                    try:
                        intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                        intent.addCategory("android.intent.category.DEFAULT")
                        intent.setData(Uri.parse(f"package:{activity.getPackageName()}"))
                        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        activity.startActivity(intent)
                    except Exception as e:
                        logging.error(f"Failed to launch Manage Storage intent: {e}")

            perms_to_request = []

            # 2. Standard Permissions (Media & Notification)
            # Notifications (Android 13+)
            if Build.VERSION.SDK_INT >= 33:
                perm_name = "android.permission.POST_NOTIFICATIONS"
                if ContextCompat.checkSelfPermission(activity, perm_name) != PackageManager.PERMISSION_GRANTED:
                    perms_to_request.append(perm_name)
            
            # Legacy Storage (Android 10 and below, or if Manage Storage is not applicable/enough for some reason)
            if Build.VERSION.SDK_INT < 30:
                for p in ["android.permission.WRITE_EXTERNAL_STORAGE", "android.permission.READ_EXTERNAL_STORAGE"]:
                    if ContextCompat.checkSelfPermission(activity, p) != PackageManager.PERMISSION_GRANTED:
                        perms_to_request.append(p)

            # Media Permissions (Android 13+) - just in case we fall back to media store
            if Build.VERSION.SDK_INT >= 33:
                 for p in ["android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO", "android.permission.READ_MEDIA_AUDIO"]:
                    if ContextCompat.checkSelfPermission(activity, p) != PackageManager.PERMISSION_GRANTED:
                        perms_to_request.append(p)

            if perms_to_request:
                logging.info(f"Requesting permissions: {perms_to_request}")
                ActivityCompat.requestPermissions(activity, perms_to_request, 101)
            else:
                logging.info("No runtime permissions needed or all granted.")
                
        except Exception as e:
            logging.error(f"Permission request failed: {e}")
            import traceback
            traceback.print_exc()

def main():
    return SanthuShare()

if __name__ == '__main__':
    main().main_loop()