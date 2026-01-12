import os
import requests
import threading
import time
import re
import uuid
from collections import deque
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
# Thread-safe queue management
QUEUE_LOCK = threading.Lock()
JOB_QUEUE = deque()  # List of dicts: {id, url, filepath, display_name, kind, item_id}
QUEUE_PAUSED = False
QUEUE_STOPPED = False

# Track queued items by ID for "Already in Queue" detection
QUEUED_ITEMS = set()  # Set of item IDs (movie/stream IDs)

DOWNLOAD_STATE = {
    "is_downloading": False,
    "current_file": "Idle",
    "progress_mb": 0,
    "total_mb": 0,
    "percent": 0,
    "queue_size": 0,
    "status": "Idle",
    "paused": False,
    "stopped": False
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
    global DOWNLOAD_STATE, QUEUE_PAUSED, QUEUE_STOPPED
    print("--- Background Worker Started ---")
    
    while True:
        # Check if stopped
        if QUEUE_STOPPED:
            time.sleep(1)
            continue
            
        # Wait if paused
        while QUEUE_PAUSED and not QUEUE_STOPPED:
            DOWNLOAD_STATE['status'] = "Paused"
            time.sleep(0.5)
        
        # Get next job from queue
        with QUEUE_LOCK:
            if len(JOB_QUEUE) == 0:
                DOWNLOAD_STATE['queue_size'] = 0
                DOWNLOAD_STATE['is_downloading'] = False
                DOWNLOAD_STATE['status'] = "Idle"
                time.sleep(1)
                continue
            
            job = JOB_QUEUE.popleft()
            job_id = job['id']
            url = job['url']
            filepath = job['filepath']
            display_name = job['display_name']
            item_id = job.get('item_id')
            
            # Remove from queued items set
            if item_id:
                QUEUED_ITEMS.discard(item_id)
        
        DOWNLOAD_STATE['queue_size'] = len(JOB_QUEUE)
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
                        # Check for pause/stop during download
                        if QUEUE_STOPPED:
                            print(f"Download stopped: {display_name}")
                            break
                        while QUEUE_PAUSED and not QUEUE_STOPPED:
                            time.sleep(0.5)
                        
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            current_mb = downloaded / (1024 * 1024)
                            DOWNLOAD_STATE['progress_mb'] = round(current_mb, 2)
                            if total: DOWNLOAD_STATE['percent'] = int((downloaded / total) * 100)
                            DOWNLOAD_STATE['status'] = "Downloading"
            
            if not QUEUE_STOPPED:
                print(f"Finished: {display_name}")

        except Exception as e:
            print(f"Failed: {e}")
            DOWNLOAD_STATE['status'] = "Error"
            time.sleep(2)
            
        finally:
            with QUEUE_LOCK:
                DOWNLOAD_STATE['queue_size'] = len(JOB_QUEUE)
            DOWNLOAD_STATE['is_downloading'] = False
            if not QUEUE_STOPPED:
                DOWNLOAD_STATE['status'] = "Idle"
            DOWNLOAD_STATE['percent'] = 0

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
        return render_template('streams_partial.html', items=data, type="movie", state=DOWNLOAD_STATE, queued_items=QUEUED_ITEMS)
    else:
        data = get_xtream_data("get_series", {"category_id": cat_id})
        return render_template('streams_partial.html', items=data, type="series", state=DOWNLOAD_STATE, queued_items=QUEUED_ITEMS)

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
    return render_template('episodes_partial.html', episodes=flat_episodes, series_name=series_name, series_id=series_id, state=DOWNLOAD_STATE, queued_items=QUEUED_ITEMS)

# --- QUEUE ACTIONS ---

@app.route('/queue/add/<kind>/<id>/<ext>')
def queue_item(kind, id, ext):
    global QUEUED_ITEMS
    
    # Check if already queued
    item_id = f"{kind}:{id}"
    if item_id in QUEUED_ITEMS:
        # Return progress bar HTML but with a message indicating already queued
        # The frontend will handle this via HTMX response
        return render_template('progress_bar.html', state=DOWNLOAD_STATE), 200
    
    title_param = request.args.get('title')
    safe_name = sanitize_filename(title_param) if title_param else f"{id}"
    filename = f"{safe_name}.{ext}"
    local_path = os.path.join(DOWNLOAD_PATH, filename)
    
    if kind == "movie":
        url = f"{XC_URL}/movie/{XC_USER}/{XC_PASS}/{id}.{ext}"
    else:
        url = f"{XC_URL}/series/{XC_USER}/{XC_PASS}/{id}.{ext}"
    
    job = {
        'id': str(uuid.uuid4()),
        'url': url,
        'filepath': local_path,
        'display_name': safe_name,
        'kind': kind,
        'item_id': item_id
    }
    
    with QUEUE_LOCK:
        JOB_QUEUE.append(job)
        QUEUED_ITEMS.add(item_id)
        DOWNLOAD_STATE['queue_size'] = len(JOB_QUEUE)
    
    return render_template('progress_bar.html', state=DOWNLOAD_STATE)

@app.route('/queue/batch_series/<series_id>')
def queue_entire_series(series_id):
    global QUEUED_ITEMS
    
    data = get_xtream_data("get_series_info", {"series_id": series_id})
    series_name = data.get('info', {}).get('name', 'Series')
    safe_series_name = sanitize_filename(series_name)
    
    added_count = 0
    with QUEUE_LOCK:
        if 'episodes' in data:
            for season_num, eps in data['episodes'].items():
                for ep in eps:
                    item_id = f"series:{ep['id']}"
                    # Skip if already queued
                    if item_id in QUEUED_ITEMS:
                        continue
                    
                    ep_title = ep.get('title', '').replace(f"{season_num}|{ep.get('episode_num')}", "").strip()
                    full_name = f"{safe_series_name} - S{ep['season']}E{ep['episode_num']} - {ep_title}"
                    safe_full_name = sanitize_filename(full_name)
                    
                    ext = ep['container_extension']
                    filename = f"{safe_full_name}.{ext}"
                    local_path = os.path.join(DOWNLOAD_PATH, filename)
                    url = f"{XC_URL}/series/{XC_USER}/{XC_PASS}/{ep['id']}.{ext}"
                    
                    job = {
                        'id': str(uuid.uuid4()),
                        'url': url,
                        'filepath': local_path,
                        'display_name': safe_full_name,
                        'kind': 'series',
                        'item_id': item_id
                    }
                    
                    JOB_QUEUE.append(job)
                    QUEUED_ITEMS.add(item_id)
                    added_count += 1
        
        DOWNLOAD_STATE['queue_size'] = len(JOB_QUEUE)
    
    return render_template('progress_bar.html', state=DOWNLOAD_STATE)

@app.route('/status')
def status():
    with QUEUE_LOCK:
        DOWNLOAD_STATE['queue_size'] = len(JOB_QUEUE)
        DOWNLOAD_STATE['paused'] = QUEUE_PAUSED
        DOWNLOAD_STATE['stopped'] = QUEUE_STOPPED
    return render_template('progress_bar.html', state=DOWNLOAD_STATE)

# --- QUEUE MANAGEMENT ENDPOINTS ---

@app.route('/queue/list')
def queue_list():
    """Get list of all queued items"""
    with QUEUE_LOCK:
        queue_items = []
        for idx, job in enumerate(JOB_QUEUE):
            queue_items.append({
                'index': idx,
                'id': job['id'],
                'name': job['display_name'],
                'kind': job.get('kind', 'unknown'),
                'item_id': job.get('item_id', '')
            })
    return jsonify({'items': queue_items, 'count': len(queue_items)})

@app.route('/queue/pause', methods=['POST'])
def queue_pause():
    """Pause all downloads"""
    global QUEUE_PAUSED
    QUEUE_PAUSED = True
    DOWNLOAD_STATE['paused'] = True
    DOWNLOAD_STATE['status'] = "Paused"
    return jsonify({'status': 'paused', 'message': 'Downloads paused'})

@app.route('/queue/resume', methods=['POST'])
def queue_resume():
    """Resume all downloads"""
    global QUEUE_PAUSED, QUEUE_STOPPED
    QUEUE_PAUSED = False
    QUEUE_STOPPED = False
    DOWNLOAD_STATE['paused'] = False
    DOWNLOAD_STATE['stopped'] = False
    DOWNLOAD_STATE['status'] = "Resuming..."
    return jsonify({'status': 'resumed', 'message': 'Downloads resumed'})

@app.route('/queue/stop', methods=['POST'])
def queue_stop():
    """Stop all downloads (current download will be interrupted)"""
    global QUEUE_STOPPED, QUEUE_PAUSED
    QUEUE_STOPPED = True
    QUEUE_PAUSED = False
    DOWNLOAD_STATE['stopped'] = True
    DOWNLOAD_STATE['paused'] = False
    DOWNLOAD_STATE['status'] = "Stopped"
    return jsonify({'status': 'stopped', 'message': 'Downloads stopped'})

@app.route('/queue/clear', methods=['POST'])
def queue_clear():
    """Clear all pending downloads from queue"""
    global QUEUED_ITEMS
    with QUEUE_LOCK:
        # Clear queue but keep currently downloading item
        JOB_QUEUE.clear()
        QUEUED_ITEMS.clear()
        DOWNLOAD_STATE['queue_size'] = 0
    return jsonify({'status': 'cleared', 'message': 'Queue cleared'})

@app.route('/queue/remove/<job_id>', methods=['DELETE', 'POST'])
def queue_remove(job_id):
    """Remove a specific item from queue by job ID"""
    global QUEUED_ITEMS
    with QUEUE_LOCK:
        for idx, job in enumerate(JOB_QUEUE):
            if job['id'] == job_id:
                removed_job = JOB_QUEUE[idx]
                JOB_QUEUE.remove(removed_job)
                item_id = removed_job.get('item_id')
                if item_id:
                    QUEUED_ITEMS.discard(item_id)
                DOWNLOAD_STATE['queue_size'] = len(JOB_QUEUE)
                return jsonify({'status': 'removed', 'message': f'Removed: {removed_job["display_name"]}'})
    return jsonify({'status': 'not_found', 'message': 'Job not found'}), 404

@app.route('/queue/reorder', methods=['POST'])
def queue_reorder():
    """Reorder queue items"""
    global QUEUED_ITEMS
    data = request.get_json()
    new_order = data.get('order', [])  # List of job IDs in new order
    
    with QUEUE_LOCK:
        # Create a map of job_id -> job
        job_map = {job['id']: job for job in JOB_QUEUE}
        
        # Rebuild queue in new order
        new_queue = deque()
        for job_id in new_order:
            if job_id in job_map:
                new_queue.append(job_map[job_id])
        
        # Add any remaining jobs not in the order list
        for job in JOB_QUEUE:
            if job['id'] not in new_order:
                new_queue.append(job)
        
        JOB_QUEUE.clear()
        JOB_QUEUE.extend(new_queue)
        DOWNLOAD_STATE['queue_size'] = len(JOB_QUEUE)
    
    return jsonify({'status': 'reordered', 'message': 'Queue reordered'})

@app.route('/queue/check/<kind>/<id>')
def queue_check(kind, id):
    """Check if an item is already in queue"""
    item_id = f"{kind}:{id}"
    is_queued = item_id in QUEUED_ITEMS
    return jsonify({'queued': is_queued, 'item_id': item_id})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
