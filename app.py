import os
import requests
import threading
import time
from flask import Flask, render_template, request

app = Flask(__name__)

# CONFIG
XC_URL = os.getenv("XC_URL", "http://provider-url.com:8080")
XC_USER = os.getenv("XC_USER", "username")
XC_PASS = os.getenv("XC_PASS", "password")
DOWNLOAD_PATH = "/downloads"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# GLOBAL STATE
DOWNLOAD_STATE = {"is_downloading": False, "filename": "", "progress_mb": 0, "total_mb": 0, "percent": 0, "status": "Idle"}

def get_xtream_data(action, params=None):
    """Generic wrapper for Xtream API calls"""
    if params is None: params = {}
    params.update({"username": XC_USER, "password": XC_PASS, "action": action})
    
    try:
        r = requests.get(f"{XC_URL}/player_api.php", params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"!!! API ERROR ({action}): {e}")
        return []

def download_worker(url, filepath):
    global DOWNLOAD_STATE
    try:
        DOWNLOAD_STATE['status'] = "Starting..."
        with requests.get(url, stream=True, headers=HEADERS) as r:
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            if total: DOWNLOAD_STATE['total_mb'] = total / (1024 * 1024)
            
            downloaded = 0
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        current_mb = downloaded / (1024 * 1024)
                        DOWNLOAD_STATE['progress_mb'] = round(current_mb, 2)
                        if total: DOWNLOAD_STATE['percent'] = int((downloaded / total) * 100)
                        DOWNLOAD_STATE['status'] = "Downloading"
        DOWNLOAD_STATE['status'] = "Complete"
        DOWNLOAD_STATE['percent'] = 100
    except Exception as e:
        DOWNLOAD_STATE['status'] = f"Error: {str(e)}"
    finally:
        time.sleep(5)
        DOWNLOAD_STATE['is_downloading'] = False

@app.route('/')
def index():
    # 1. Get Movies Categories
    movie_cats = get_xtream_data("get_vod_categories")
    # 2. Get Series Categories
    series_cats = get_xtream_data("get_series_categories")
    
    # 3. Tag them so we know which API to call later
    # We create a new list of dicts with a 'type' key
    combined = []
    if isinstance(movie_cats, list):
        for c in movie_cats:
            c['type'] = 'movie'
            c['display_name'] = f"[Movie] {c.get('category_name')}"
            combined.append(c)
            
    if isinstance(series_cats, list):
        for c in series_cats:
            c['type'] = 'series'
            c['display_name'] = f"[Series] {c.get('category_name')}"
            combined.append(c)
            
    return render_template('index.html', categories=combined)

@app.route('/streams')
def streams():
    # We expect format "type:id", e.g. "movie:123" or "series:456"
    selection = request.args.get('category')
    if not selection or ":" not in selection: return ""
    
    cat_type, cat_id = selection.split(":")
    
    if cat_type == "movie":
        data = get_xtream_data("get_vod_streams", {"category_id": cat_id})
        return render_template('streams_partial.html', items=data, type="movie")
    
    elif cat_type == "series":
        # 'get_series' returns the TV Shows, not the episodes
        data = get_xtream_data("get_series", {"category_id": cat_id})
        return render_template('streams_partial.html', items=data, type="series")

@app.route('/episodes/<series_id>')
def episodes(series_id):
    # Fetch details for one specific TV Show
    data = get_xtream_data("get_series_info", {"series_id": series_id})
    
    # Xtream returns dict with 'episodes' key containing a dict of seasons
    # We need to flatten this into a simple list for the template
    flat_episodes = []
    
    if 'episodes' in data:
        for season_num, eps in data['episodes'].items():
            for ep in eps:
                flat_episodes.append(ep)
                
    return render_template('episodes_partial.html', episodes=flat_episodes)

@app.route('/download/<kind>/<id>/<ext>')
def start_download(kind, id, ext):
    global DOWNLOAD_STATE
    if DOWNLOAD_STATE['is_downloading']: return "<button disabled>⚠️ Busy</button>"
    
    filename = f"{id}.{ext}"
    local_path = os.path.join(DOWNLOAD_PATH, filename)
    
    # URL structure differs for Series vs Movies
    if kind == "movie":
        url = f"{XC_URL}/movie/{XC_USER}/{XC_PASS}/{id}.{ext}"
    else:
        url = f"{XC_URL}/series/{XC_USER}/{XC_PASS}/{id}.{ext}"

    DOWNLOAD_STATE = {"is_downloading": True, "filename": filename, "progress_mb": 0, "total_mb": 0, "percent": 0, "status": "Starting"}
    threading.Thread(target=download_worker, args=(url, local_path)).start()
    return render_template('progress_bar.html')

@app.route('/status')
def status():
    return render_template('progress_bar.html', state=DOWNLOAD_STATE)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)