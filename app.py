import os
import requests
import threading
import time
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# CONFIG
XC_URL = os.getenv("XC_URL", "http://provider-url.com:8080")
XC_USER = os.getenv("XC_USER", "username")
XC_PASS = os.getenv("XC_PASS", "password")
DOWNLOAD_PATH = "/downloads"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# GLOBAL STATE (Simple In-Memory Database)
# In a real app, you'd use Redis/SQLite, but this works for a home lab.
DOWNLOAD_STATE = {
    "is_downloading": False,
    "filename": "",
    "progress_mb": 0,
    "total_mb": 0,
    "percent": 0,
    "status": "Idle"
}

def get_xtream_data(action, category_id=None):
    """Wrapper for API calls"""
    params = {"username": XC_USER, "password": XC_PASS, "action": action}
    if category_id: params['category_id'] = category_id
    
    try:
        r = requests.get(f"{XC_URL}/player_api.php", params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"!!! API ERROR: {e}")
        return []

# --- BACKGROUND WORKER ---
def download_worker(url, filepath):
    global DOWNLOAD_STATE
    try:
        DOWNLOAD_STATE['status'] = "Starting..."
        
        with requests.get(url, stream=True, headers=HEADERS) as r:
            r.raise_for_status()
            
            # Get Total Size (if provided by server)
            total_length = r.headers.get('content-length')
            if total_length:
                DOWNLOAD_STATE['total_mb'] = int(total_length) / (1024 * 1024)
            
            downloaded = 0
            
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024): # 1MB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Update Global State
                        current_mb = downloaded / (1024 * 1024)
                        DOWNLOAD_STATE['progress_mb'] = round(current_mb, 2)
                        
                        if total_length:
                            DOWNLOAD_STATE['percent'] = int((downloaded / int(total_length)) * 100)
                        
                        DOWNLOAD_STATE['status'] = "Downloading"

        DOWNLOAD_STATE['status'] = "Complete"
        DOWNLOAD_STATE['percent'] = 100
        
    except Exception as e:
        DOWNLOAD_STATE['status'] = f"Error: {str(e)}"
    finally:
        time.sleep(5) # Keep "Complete" msg for 5 seconds
        DOWNLOAD_STATE['is_downloading'] = False # Release Lock

# --- ROUTES ---

@app.route('/')
def index():
    categories = get_xtream_data("get_vod_categories")
    return render_template('index.html', categories=categories)

@app.route('/streams')
def streams():
    cat_id = request.args.get('category')
    streams = get_xtream_data("get_vod_streams", cat_id)
    if not streams: return "<div style='text-align:center'>No streams found.</div>"
    return render_template('streams_partial.html', streams=streams)

@app.route('/download/<stream_id>/<extension>')
def start_download(stream_id, extension):
    global DOWNLOAD_STATE
    
    # 1. Check Lock
    if DOWNLOAD_STATE['is_downloading']:
        return "<button class='contrast' disabled>⚠️ Busier than allowed (1 connection)</button>"

    # 2. Setup Download
    filename = f"{stream_id}.{extension}"
    local_path = os.path.join(DOWNLOAD_PATH, filename)
    direct_url = f"{XC_URL}/movie/{XC_USER}/{XC_PASS}/{filename}"
    
    # 3. Reset State
    DOWNLOAD_STATE = {
        "is_downloading": True,
        "filename": filename,
        "progress_mb": 0,
        "total_mb": 0,
        "percent": 0,
        "status": "Starting"
    }

    # 4. Start Background Thread
    thread = threading.Thread(target=download_worker, args=(direct_url, local_path))
    thread.start()
    
    # 5. Return the "Polling Bar" immediately
    return render_template('progress_bar.html')

@app.route('/status')
def status():
    """Called every 1 second by the frontend to update the bar"""
    return render_template('progress_bar.html', state=DOWNLOAD_STATE)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)