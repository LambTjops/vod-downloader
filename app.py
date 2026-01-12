import os
import requests
import threading
import time
import re
import queue
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

# --- GLOBAL STATE & QUEUE ---
JOB_QUEUE = queue.Queue()

DOWNLOAD_STATE = {
    "is_downloading": False,
    "current_file": "Idle",
    "progress_mb": 0,
    "total_mb": 0,
    "percent": 0,
    "queue_size": 0,
    "status": "Idle"
}

def sanitize_filename(name):
    clean = re.sub(r'[<>:"/\\|?*]', '', name)
    return clean.strip()

def get_xtream_data(action, params=None):
    if params is None: params = {}
    params.update({"username": XC_USER, "password": XC_PASS, "action": action})
    try:
        r = requests.get(f"{XC_URL}/player_api.php", params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"!!! API ERROR ({action}): {e}")
        return []

# --- BACKGROUND WORKER ---
def worker_loop():
    global DOWNLOAD_STATE
    print("--- Background Worker Started ---")
    
    while True:
        DOWNLOAD_STATE['queue_size'] = JOB_QUEUE.qsize()
        url, filepath, display_name = JOB_QUEUE.get()
        
        DOWNLOAD_STATE['is_downloading'] = True
        DOWNLOAD_STATE['current_file'] = display_name
        DOWNLOAD_STATE['status'] = "Starting..."
        DOWNLOAD_STATE['percent'] = 0
        
        try:
            print(f"Starting Download: {display_name}")
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
            print(f"Finished: {display_name}")

        except Exception as e:
            print(f"Failed: {e}")
            DOWNLOAD_STATE['status'] = "Error"
            time.sleep(2)
            
        finally:
            JOB_QUEUE.task_done()
            DOWNLOAD_STATE['is_downloading'] = False
            DOWNLOAD_STATE['status'] = "Idle"
            DOWNLOAD_STATE['percent'] = 0
            DOWNLOAD_STATE['queue_size'] = JOB_QUEUE.qsize()

threading.Thread(target=worker_loop, daemon=True).start()


# --- ROUTES ---

@app.route('/')
def index():
    movie_cats = get_xtream_data("get_vod_categories")
    series_cats = get_xtream_data("get_series_categories")
    
    combined = []
    
    # Corrected keys for index.html compatibility
    if isinstance(movie_cats, list):
        for c in movie_cats:
            combined.append({
                'type': 'movie', 
                'category_id': c['category_id'], 
                'display_name': f"[Movie] {c['category_name']}"
            })
            
    if isinstance(series_cats, list):
        for c in series_cats:
            combined.append({
                'type': 'series', 
                'category_id': c['category_id'], 
                'display_name': f"[Series] {c['category_name']}"
            })
            
    return render_template('index.html', categories=combined)

@app.route('/streams')
def streams():
    selection = request.args.get('category')
    if not selection or ":" not in selection: return ""
    cat_type, cat_id = selection.split(":")
    
    # FIX: We now pass state=DOWNLOAD_STATE so the progress bar doesn't crash
    if cat_type == "movie":
        data = get_xtream_data("get_vod_streams", {"category_id": cat_id})
        return render_template('streams_partial.html', items=data, type="movie", state=DOWNLOAD_STATE)
    else:
        data = get_xtream_data("get_series", {"category_id": cat_id})
        return render_template('streams_partial.html', items=data, type="series", state=DOWNLOAD_STATE)

@app.route('/episodes/<series_id>')
def episodes(series_id):
    data = get_xtream_data("get_series_info", {"series_id": series_id})
    series_info = data.get('info', {})
    series_name = series_info.get('name', 'Series')
    
    flat_episodes = []
    if 'episodes' in data:
        for season_num, eps in data['episodes'].items():
            for ep in eps:
                flat_episodes.append(ep)
                
    # FIX: Pass state=DOWNLOAD_STATE here too
    return render_template('episodes_partial.html', episodes=flat_episodes, series_name=series_name, series_id=series_id, state=DOWNLOAD_STATE)

# --- QUEUE ACTIONS ---

@app.route('/queue/add/<kind>/<id>/<ext>')
def queue_item(kind, id, ext):
    title_param = request.args.get('title')
    safe_name = sanitize_filename(title_param) if title_param else f"{id}"
    filename = f"{safe_name}.{ext}"
    local_path = os.path.join(DOWNLOAD_PATH, filename)
    
    if kind == "movie":
        url = f"{XC_URL}/movie/{XC_USER}/{XC_PASS}/{id}.{ext}"
    else:
        url = f"{XC_URL}/series/{XC_USER}/{XC_PASS}/{id}.{ext}"
    
    JOB_QUEUE.put((url, local_path, safe_name))
    
    # Update size immediately for the UI
    DOWNLOAD_STATE['queue_size'] = JOB_QUEUE.qsize()
    return render_template('progress_bar.html', state=DOWNLOAD_STATE)

@app.route('/queue/batch_series/<series_id>')
def queue_entire_series(series_id):
    data = get_xtream_data("get_series_info", {"series_id": series_id})
    series_name = data.get('info', {}).get('name', 'Series')
    safe_series_name = sanitize_filename(series_name)
    
    if 'episodes' in data:
        for season_num, eps in data['episodes'].items():
            for ep in eps:
                ep_title = ep.get('title', '').replace(f"{season_num}|{ep.get('episode_num')}", "").strip()
                full_name = f"{safe_series_name} - S{ep['season']}E{ep['episode_num']} - {ep_title}"
                safe_full_name = sanitize_filename(full_name)
                
                ext = ep['container_extension']
                filename = f"{safe_full_name}.{ext}"
                local_path = os.path.join(DOWNLOAD_PATH, filename)
                url = f"{XC_URL}/series/{XC_USER}/{XC_PASS}/{ep['id']}.{ext}"
                
                JOB_QUEUE.put((url, local_path, safe_full_name))
                
    DOWNLOAD_STATE['queue_size'] = JOB_QUEUE.qsize()
    return render_template('progress_bar.html', state=DOWNLOAD_STATE)

@app.route('/status')
def status():
    DOWNLOAD_STATE['queue_size'] = JOB_QUEUE.qsize()
    return render_template('progress_bar.html', state=DOWNLOAD_STATE)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)