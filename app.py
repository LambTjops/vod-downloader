import os
import requests
import threading
import time
import re
import uuid
import json
from collections import deque
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# CONFIG
XC_URL = os.getenv("XC_URL", "http://provider-url.com:8080")
XC_USER = os.getenv("XC_USER", "username")
XC_PASS = os.getenv("XC_PASS", "password")
DOWNLOAD_PATH = os.getenv("DOWNLOAD_PATH", "/downloads")
# Persistent database file location - can be overridden via environment variable
DB_FILE_PATH = os.getenv("DB_FILE_PATH", None)
if DB_FILE_PATH:
    DOWNLOADED_DB_FILE = DB_FILE_PATH
else:
    # Default: same directory as app.py
    DOWNLOADED_DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloaded_items.json")

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

# Track downloaded items by item_id (persistent across restarts)
# Format: {item_id: {"downloaded_at": timestamp, "filename": str, "size_mb": float}}
DOWNLOADED_ITEMS = {}  # Dict of item_id -> download info

# Track scanned files by filename pattern (for quick matching)
# Format: {filename_pattern: {"filename": str, "size_mb": float, "scanned_at": timestamp}}
SCANNED_FILES = {}  # Dict of normalized filename -> file info

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

def check_file_exists(filepath):
    """Check if a file already exists and has content"""
    if os.path.exists(filepath):
        # Check if file has content (at least 1MB to avoid empty/corrupted files)
        return os.path.getsize(filepath) > 1024 * 1024
    return False

def load_downloaded_items():
    """Load downloaded items from persistent JSON file"""
    global DOWNLOADED_ITEMS
    print(f"Loading downloaded items database from: {DOWNLOADED_DB_FILE}")
    if os.path.exists(DOWNLOADED_DB_FILE):
        try:
            with open(DOWNLOADED_DB_FILE, 'r') as f:
                DOWNLOADED_ITEMS = json.load(f)
            print(f"✓ Successfully loaded {len(DOWNLOADED_ITEMS)} downloaded items from database")
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in database file: {e}")
            print(f"Backing up corrupted file and creating new one...")
            try:
                backup_file = DOWNLOADED_DB_FILE + ".backup"
                os.rename(DOWNLOADED_DB_FILE, backup_file)
            except:
                pass
            DOWNLOADED_ITEMS = {}
        except Exception as e:
            print(f"ERROR: Failed to load downloaded items database: {e}")
            import traceback
            traceback.print_exc()
            DOWNLOADED_ITEMS = {}
    else:
        print(f"Database file not found at {DOWNLOADED_DB_FILE}, creating new database")
        DOWNLOADED_ITEMS = {}
        # Also scan current download folder to populate initial database
        scan_and_update_downloaded_files()

def save_downloaded_items():
    """Save downloaded items to persistent JSON file"""
    print(f"[DEBUG] save_downloaded_items() called - File: {DOWNLOADED_DB_FILE}, Items: {len(DOWNLOADED_ITEMS)}")
    try:
        # Ensure directory exists
        db_dir = os.path.dirname(DOWNLOADED_DB_FILE)
        print(f"[DEBUG] Database directory: {db_dir}, exists: {os.path.exists(db_dir) if db_dir else 'N/A'}")
        
        if db_dir and not os.path.exists(db_dir):
            print(f"[DEBUG] Creating database directory: {db_dir}")
            os.makedirs(db_dir, exist_ok=True)
            print(f"[DEBUG] Created database directory: {db_dir}")
        
        # Check if directory is writable
        if db_dir and not os.access(db_dir, os.W_OK):
            print(f"ERROR: Directory {db_dir} is not writable!")
            return False
        
        # Write to temporary file first, then rename (atomic operation)
        temp_file = DOWNLOADED_DB_FILE + '.tmp'
        print(f"[DEBUG] Writing to temp file: {temp_file}")
        with open(temp_file, 'w') as f:
            json.dump(DOWNLOADED_ITEMS, f, indent=2)
        
        print(f"[DEBUG] Temp file written, size: {os.path.getsize(temp_file)} bytes")
        
        # Atomic rename
        print(f"[DEBUG] Renaming {temp_file} to {DOWNLOADED_DB_FILE}")
        os.replace(temp_file, DOWNLOADED_DB_FILE)
        
        # Verify file was created
        if os.path.exists(DOWNLOADED_DB_FILE):
            file_size = os.path.getsize(DOWNLOADED_DB_FILE)
            print(f"✓ Saved {len(DOWNLOADED_ITEMS)} downloaded items to {DOWNLOADED_DB_FILE} ({file_size} bytes)")
            return True
        else:
            print(f"ERROR: File was not created after rename: {DOWNLOADED_DB_FILE}")
            return False
    except PermissionError as e:
        print(f"ERROR: Permission denied writing to {DOWNLOADED_DB_FILE}: {e}")
        print(f"Please check file permissions for: {os.path.dirname(DOWNLOADED_DB_FILE)}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"ERROR: Failed to save downloaded items database to {DOWNLOADED_DB_FILE}: {e}")
        import traceback
        traceback.print_exc()
        return False

def mark_item_downloaded(item_id, filename, filepath=None):
    """
    Mark an item as downloaded and save to persistent storage.
    
    Args:
        item_id: Unique identifier in format "kind:id" (e.g., "movie:123")
        filename: Name of the downloaded file
        filepath: Optional full path to the file (for size calculation)
    
    Returns:
        bool: True if successful, False otherwise
    """
    global DOWNLOADED_ITEMS
    if not item_id:
        print("ERROR: Cannot mark item as downloaded - item_id is None")
        return False
    
    file_size_mb = 0
    if filepath and os.path.exists(filepath):
        file_size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 2)
    
    DOWNLOADED_ITEMS[item_id] = {
        "downloaded_at": time.time(),
        "filename": filename,
        "size_mb": file_size_mb
    }
    
    # Save to database
    if save_downloaded_items():
        print(f"✓ Marked {item_id} as downloaded - Database: {DOWNLOADED_DB_FILE}")
        return True
    else:
        print(f"ERROR: Failed to save download record for {item_id}")
        return False

def is_item_downloaded(item_id):
    """Check if an item has been downloaded (persistent check)"""
    return item_id in DOWNLOADED_ITEMS

def scan_and_update_downloaded_files():
    """Scan download directory and update DOWNLOADED_ITEMS database"""
    global DOWNLOADED_ITEMS
    if not os.path.exists(DOWNLOAD_PATH):
        os.makedirs(DOWNLOAD_PATH, exist_ok=True)
        return
    
    # This is a one-time scan to populate the database
    # We track by item_id, not filepath, so moving files won't affect tracking
    updated = False
    for filename in os.listdir(DOWNLOAD_PATH):
        filepath = os.path.join(DOWNLOAD_PATH, filename)
        if os.path.isfile(filepath) and os.path.getsize(filepath) > 1024 * 1024:
            # Try to infer item_id from filename (this is best-effort)
            # For new downloads, we'll track by item_id directly
            # This scan is mainly for initial population
            pass
    
    if updated:
        save_downloaded_items()

# ============================================================================
# INITIALIZATION
# ============================================================================
print("=" * 70)
print("VOD Downloader - Starting Application")
print("=" * 70)
print(f"Download Path: {DOWNLOAD_PATH}")
print(f"Database File: {DOWNLOADED_DB_FILE}")
print(f"Database Directory: {os.path.dirname(DOWNLOADED_DB_FILE)}")
print(f"Database Directory Exists: {os.path.exists(os.path.dirname(DOWNLOADED_DB_FILE))}")
print("=" * 70)

# ============================================================================
# INITIALIZATION
# ============================================================================
print("=" * 70)
print("VOD Downloader - Starting Application")
print("=" * 70)
print(f"Download Path: {DOWNLOAD_PATH}")
print(f"Database File: {DOWNLOADED_DB_FILE}")
print(f"Database Directory: {os.path.dirname(DOWNLOADED_DB_FILE)}")
print(f"Database Directory Exists: {os.path.exists(os.path.dirname(DOWNLOADED_DB_FILE))}")
print("=" * 70)

# Initialize downloaded items on startup
load_downloaded_items()

# Note: auto_scan_on_startup() is called after helper functions are defined (see end of file)

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
                # Mark as downloaded if file exists and has content
                if check_file_exists(filepath) and item_id:
                    mark_item_downloaded(item_id, os.path.basename(filepath), filepath)
                elif not item_id:
                    print(f"WARNING: No item_id for completed download: {display_name}")

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
        # Add downloaded status to each item (check by item_id and scanned files)
        for item in data:
            item_id = f"movie:{item.get('stream_id', '')}"
            # First check if already in database
            if is_item_downloaded(item_id):
                item['_is_downloaded'] = True
            else:
                # Check if matches a scanned file
                matched_file = match_file_to_item(item, item_id, "movie")
                if matched_file:
                    # Auto-mark as downloaded if file matches
                    filepath = os.path.join(DOWNLOAD_PATH, matched_file['filename'])
                    if mark_item_downloaded(item_id, matched_file['filename'], filepath):
                        item['_is_downloaded'] = True
                        print(f"[MATCH] Auto-matched movie: {item.get('name')} -> {matched_file['filename']}")
                    else:
                        item['_is_downloaded'] = False
                else:
                    item['_is_downloaded'] = False
        return render_template('streams_partial.html', items=data, type="movie", state=DOWNLOAD_STATE, queued_items=QUEUED_ITEMS, downloaded_items=DOWNLOADED_ITEMS)
    else:
        data = get_xtream_data("get_series", {"category_id": cat_id})
        return render_template('streams_partial.html', items=data, type="series", state=DOWNLOAD_STATE, queued_items=QUEUED_ITEMS, downloaded_items=DOWNLOADED_ITEMS)

@app.route('/episodes/<series_id>')
def episodes(series_id):
    data = get_xtream_data("get_series_info", {"series_id": series_id})
    series_info = data.get('info', {})
    series_name = series_info.get('name', 'Series')
    
    # Keep episodes grouped by season for better organization
    episodes_by_season = {}
    flat_episodes = []
    
    if 'episodes' in data:
        series_name = series_info.get('name', 'Series')
        for season_num, eps in data['episodes'].items():
            season_episodes = []
            for ep in eps:
                # Check if episode is already downloaded (by item_id)
                item_id = f"series:{ep.get('id', '')}"
                ep['_series_name'] = series_name
                # First check if already in database
                if is_item_downloaded(item_id):
                    ep['_is_downloaded'] = True
                else:
                    # Check if matches a scanned file
                    matched_file = match_file_to_item(ep, item_id, "series")
                    if matched_file:
                        # Auto-mark as downloaded if file matches
                        filepath = os.path.join(DOWNLOAD_PATH, matched_file['filename'])
                        if mark_item_downloaded(item_id, matched_file['filename'], filepath):
                            ep['_is_downloaded'] = True
                            print(f"[MATCH] Auto-matched episode: {series_name} S{ep.get('season')}E{ep.get('episode_num')} -> {matched_file['filename']}")
                        else:
                            ep['_is_downloaded'] = False
                    else:
                        ep['_is_downloaded'] = False
                ep['_item_id'] = item_id
                season_episodes.append(ep)
                flat_episodes.append(ep)
            episodes_by_season[season_num] = season_episodes
                
    # FIX: Pass state=DOWNLOAD_STATE here too
    return render_template('episodes_partial.html', 
                         episodes=flat_episodes, 
                         episodes_by_season=episodes_by_season,
                         series_name=series_name, 
                         series_id=series_id, 
                         state=DOWNLOAD_STATE, 
                         queued_items=QUEUED_ITEMS)

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
    
    # Check if already downloaded (persistent check)
    if is_item_downloaded(item_id):
        # Item already downloaded, don't add to queue
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
                    
                    # Skip if already downloaded (persistent check)
                    if is_item_downloaded(item_id):
                        continue
                    
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

@app.route('/queue/scan', methods=['POST'])
def scan_downloads():
    """Manually scan download directory for existing files"""
    scan_and_update_downloaded_files()
    return jsonify({'status': 'scanned', 'count': len(DOWNLOADED_ITEMS), 'message': f'Database contains {len(DOWNLOADED_ITEMS)} downloaded items'})

@app.route('/queue/downloaded', methods=['GET'])
def list_downloaded():
    """Get list of all downloaded items"""
    return jsonify({
        'items': DOWNLOADED_ITEMS,
        'count': len(DOWNLOADED_ITEMS)
    })

@app.route('/queue/downloaded/<item_id>', methods=['DELETE', 'POST'])
def remove_downloaded(item_id):
    """Remove an item from downloaded list (if file was deleted manually)"""
    global DOWNLOADED_ITEMS
    if item_id in DOWNLOADED_ITEMS:
        del DOWNLOADED_ITEMS[item_id]
        save_downloaded_items()
        return jsonify({'status': 'removed', 'message': f'Removed {item_id} from downloaded list'})
    return jsonify({'status': 'not_found', 'message': 'Item not found'}), 404

@app.route('/queue/db_info', methods=['GET'])
def db_info():
    """Get information about the download database file"""
    db_exists = os.path.exists(DOWNLOADED_DB_FILE)
    db_size = 0
    if db_exists:
        db_size = os.path.getsize(DOWNLOADED_DB_FILE)
    
    return jsonify({
        'db_file': DOWNLOADED_DB_FILE,
        'db_exists': db_exists,
        'db_size': db_size,
        'db_size_kb': round(db_size / 1024, 2) if db_exists else 0,
        'item_count': len(DOWNLOADED_ITEMS),
        'download_path': DOWNLOAD_PATH,
        'download_path_exists': os.path.exists(DOWNLOAD_PATH),
        'message': f'Database file location: {DOWNLOADED_DB_FILE}'
    })

@app.route('/queue/mark_downloaded/<kind>/<id>', methods=['POST'])
def mark_downloaded_manual(kind, id):
    """Manually mark an item as downloaded"""
    item_id = f"{kind}:{id}"
    
    # Try to find the file in download directory
    filename = None
    filepath = None
    
    # Get item info to construct filename
    if kind == "movie":
        data = get_xtream_data("get_vod_streams", {"stream_id": id})
        if data and len(data) > 0:
            item = data[0]
            safe_name = sanitize_filename(item.get('name', f'movie_{id}'))
            ext = item.get('container_extension', 'mp4')
            filename = f"{safe_name}.{ext}"
            filepath = os.path.join(DOWNLOAD_PATH, filename)
    else:  # series
        # For series episodes, try to get episode info
        # This can be slow, so we'll try but fallback to simple name if it fails
        try:
            # Try to get episode info from request parameter if available
            series_id_param = request.args.get('series_id')
            if series_id_param:
                series_info = get_xtream_data("get_series_info", {"series_id": series_id_param})
                if 'episodes' in series_info:
                    for season_num, eps in series_info['episodes'].items():
                        for ep in eps:
                            if str(ep.get('id')) == str(id):
                                series_name = series_info.get('info', {}).get('name', 'Series')
                                safe_series_name = sanitize_filename(series_name)
                                ep_title = ep.get('title', '').replace(f"{season_num}|{ep.get('episode_num')}", "").strip()
                                full_name = f"{safe_series_name} - S{ep['season']}E{ep['episode_num']} - {ep_title}"
                                safe_full_name = sanitize_filename(full_name)
                                ext = ep.get('container_extension', 'mp4')
                                filename = f"{safe_full_name}.{ext}"
                                filepath = os.path.join(DOWNLOAD_PATH, filename)
                                break
            
            # Fallback to simple name if we couldn't find episode info
            if not filename:
                filename = f"series_episode_{id}"
        except Exception as e:
            print(f"Warning: Could not get episode info for {id}: {e}")
            filename = f"series_episode_{id}"
    
    try:
        print(f"[DEBUG] mark_downloaded_manual called: kind={kind}, id={id}, item_id={item_id}")
        print(f"[DEBUG] Database file path: {DOWNLOADED_DB_FILE}")
        print(f"[DEBUG] Database file exists before: {os.path.exists(DOWNLOADED_DB_FILE)}")
        db_dir = os.path.dirname(DOWNLOADED_DB_FILE)
        print(f"[DEBUG] Directory: {db_dir}, exists: {os.path.exists(db_dir)}, writable: {os.access(db_dir, os.W_OK) if os.path.exists(db_dir) else 'N/A'}")
        
        success = mark_item_downloaded(item_id, filename, filepath)
        print(f"[DEBUG] mark_item_downloaded returned: {success}")
        print(f"[DEBUG] Database file exists after: {os.path.exists(DOWNLOADED_DB_FILE)}")
        
        if success:
            print(f"Manually marked {item_id} as downloaded (file: {filename})")
            return jsonify({
                'status': 'marked',
                'item_id': item_id,
                'filename': filename,
                'db_file': DOWNLOADED_DB_FILE,
                'db_exists': os.path.exists(DOWNLOADED_DB_FILE),
                'message': f'Marked {item_id} as downloaded. Database saved to: {DOWNLOADED_DB_FILE}'
            })
        else:
            error_msg = f'Failed to save to database. Check server logs. Database file: {DOWNLOADED_DB_FILE}'
            print(f"ERROR: {error_msg}")
            return jsonify({
                'status': 'error',
                'item_id': item_id,
                'db_file': DOWNLOADED_DB_FILE,
                'db_exists': os.path.exists(DOWNLOADED_DB_FILE),
                'message': error_msg
            }), 500
    except Exception as e:
        print(f"ERROR in mark_downloaded_manual: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'item_id': item_id,
            'db_file': DOWNLOADED_DB_FILE,
            'error': str(e),
            'message': f'Error marking as downloaded: {str(e)}. Database file: {DOWNLOADED_DB_FILE}'
        }), 500

@app.route('/queue/mark_downloaded_batch', methods=['POST'])
def mark_downloaded_batch():
    """Mark multiple items as downloaded"""
    data = request.get_json()
    item_ids = data.get('item_ids', [])
    marked_count = 0
    
    for item_id in item_ids:
        if ':' in item_id:
            kind, id = item_id.split(':', 1)
            # Try to find file
            filename = f"{kind}_{id}"
            filepath = os.path.join(DOWNLOAD_PATH, filename)
            mark_item_downloaded(item_id, filename, filepath)
            marked_count += 1
    
    return jsonify({
        'status': 'marked',
        'count': marked_count,
        'message': f'Marked {marked_count} items as downloaded'
    })

@app.route('/queue/mark_all_episodes_downloaded/<series_id>', methods=['POST'])
def mark_all_episodes_downloaded(series_id):
    """Mark all episodes in a series as downloaded"""
    data = get_xtream_data("get_series_info", {"series_id": series_id})
    marked_count = 0
    
    if 'episodes' in data:
        for season_num, eps in data['episodes'].items():
            for ep in eps:
                item_id = f"series:{ep.get('id', '')}"
                if not is_item_downloaded(item_id):
                    ep_title = ep.get('title', '').replace(f"{season_num}|{ep.get('episode_num')}", "").strip()
                    series_name = data.get('info', {}).get('name', 'Series')
                    safe_series_name = sanitize_filename(series_name)
                    full_name = f"{safe_series_name} - S{ep['season']}E{ep['episode_num']} - {ep_title}"
                    safe_full_name = sanitize_filename(full_name)
                    ext = ep.get('container_extension', 'mp4')
                    filename = f"{safe_full_name}.{ext}"
                    filepath = os.path.join(DOWNLOAD_PATH, filename)
                    mark_item_downloaded(item_id, filename, filepath)
                    marked_count += 1
    
    return jsonify({
        'status': 'marked',
        'count': marked_count,
        'message': f'Marked {marked_count} episodes as downloaded'
    })

def normalize_filename_for_matching(filename):
    """Normalize filename for matching - remove extension, lowercase, remove special chars"""
    base = os.path.splitext(filename)[0].lower()
    # Remove common separators and normalize spaces
    base = re.sub(r'[_\-\s]+', ' ', base)
    return base.strip()

def extract_episode_info(filename):
    """Extract series name, season, and episode from filename"""
    base = os.path.splitext(filename)[0]
    # Look for S##E## pattern
    season_match = re.search(r'S(\d+)E(\d+)', base, re.IGNORECASE)
    if season_match:
        season = int(season_match.group(1))
        episode = int(season_match.group(2))
        # Try to extract series name (everything before S##E##)
        series_match = re.search(r'^(.+?)\s*-\s*S\d+E\d+', base, re.IGNORECASE)
        series_name = series_match.group(1).strip() if series_match else None
        return {
            'type': 'episode',
            'season': season,
            'episode': episode,
            'series_name': series_name,
            'normalized_series': normalize_filename_for_matching(series_name) if series_name else None
        }
    return {'type': 'movie', 'normalized_name': normalize_filename_for_matching(base)}

@app.route('/queue/scan_files', methods=['POST'])
def scan_files_and_match():
    """Scan download directory and store file info for later matching"""
    print("[SCAN] Starting file scan...")
    try:
        if not os.path.exists(DOWNLOAD_PATH):
            error_msg = f'Download directory does not exist: {DOWNLOAD_PATH}'
            print(f"[SCAN] ERROR: {error_msg}")
            return jsonify({'status': 'error', 'message': error_msg}), 404
        
        global SCANNED_FILES
        SCANNED_FILES = {}  # Reset scanned files
        files_found = []
        
        print("[SCAN] Scanning download directory...")
        file_list = os.listdir(DOWNLOAD_PATH)
        print(f"[SCAN] Found {len(file_list)} items in download directory")
        
        for filename in file_list:
            filepath = os.path.join(DOWNLOAD_PATH, filename)
            if os.path.isfile(filepath) and os.path.getsize(filepath) > 1024 * 1024:
                size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 2)
                
                # Extract metadata from filename
                file_info = extract_episode_info(filename)
                file_info.update({
                    'filename': filename,
                    'size_mb': size_mb,
                    'scanned_at': time.time()
                })
                
                # Store normalized for matching
                normalized = normalize_filename_for_matching(filename)
                SCANNED_FILES[normalized] = file_info
                
                files_found.append({
                    'filename': filename,
                    'size_mb': size_mb,
                    'type': file_info.get('type', 'unknown'),
                    'season': file_info.get('season'),
                    'episode': file_info.get('episode'),
                    'series_name': file_info.get('series_name')
                })
        
        print(f"[SCAN] Complete: Scanned {len(files_found)} files")
        print(f"[SCAN] Files stored for matching. They will be matched when you view categories.")
        
        # Now try to match with items already in DOWNLOADED_ITEMS to avoid duplicates
        # This is optional - just a quick check
        
        return jsonify({
            'status': 'scanned',
            'files_found': len(files_found),
            'files': files_found,
            'message': f'Scanned {len(files_found)} files. Files will be matched when you view categories.'
        })
    except Exception as e:
        error_msg = f"Fatal error during file scan: {e}"
        print(f"[SCAN] FATAL ERROR: {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': error_msg,
            'error_type': type(e).__name__
        }), 500

def match_file_to_item(item, item_id, item_type):
    """Check if an item matches any scanned file"""
    global SCANNED_FILES
    
    if not SCANNED_FILES:
        return None
    
    if item_type == "movie":
        # For movies, match by name
        movie_name = item.get('name', '')
        normalized_movie = normalize_filename_for_matching(movie_name)
        
        # Check if any scanned file matches this movie name
        for normalized_file, file_info in SCANNED_FILES.items():
            if file_info.get('type') == 'movie':
                # Check if movie name is in filename or vice versa
                if normalized_movie in normalized_file or normalized_file in normalized_movie:
                    # Additional check: names should be similar length (not just substring)
                    if abs(len(normalized_movie) - len(normalized_file)) < max(len(normalized_movie), len(normalized_file)) * 0.5:
                        return file_info
    else:
        # For series episodes, match by season/episode and series name
        series_name = item.get('_series_name') or item.get('series_name', '')
        season = item.get('season')
        episode_num = item.get('episode_num')
        
        if season and episode_num and series_name:
            normalized_series = normalize_filename_for_matching(series_name)
            
            for normalized_file, file_info in SCANNED_FILES.items():
                if file_info.get('type') == 'episode':
                    if (file_info.get('season') == season and 
                        file_info.get('episode') == episode_num):
                        # Check series name match
                        file_series = file_info.get('normalized_series', '')
                        if normalized_series in file_series or file_series in normalized_series:
                            return file_info
    
    return None

# Auto-scan download folder on startup (called after helper functions are defined)
def auto_scan_on_startup():
    """Auto-scan download folder on startup to populate scanned files"""
    print("[STARTUP] Auto-scanning download folder...")
    try:
        if os.path.exists(DOWNLOAD_PATH):
            global SCANNED_FILES
            SCANNED_FILES = {}
            file_count = 0
            
            file_list = os.listdir(DOWNLOAD_PATH)
            for filename in file_list:
                filepath = os.path.join(DOWNLOAD_PATH, filename)
                if os.path.isfile(filepath) and os.path.getsize(filepath) > 1024 * 1024:
                    size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 2)
                    
                    # Extract metadata from filename
                    file_info = extract_episode_info(filename)
                    file_info.update({
                        'filename': filename,
                        'size_mb': size_mb,
                        'scanned_at': time.time()
                    })
                    
                    # Store normalized for matching
                    normalized = normalize_filename_for_matching(filename)
                    SCANNED_FILES[normalized] = file_info
                    file_count += 1
            
            print(f"[STARTUP] ✓ Auto-scan complete: Found {file_count} files ready for matching")
        else:
            print(f"[STARTUP] Download path does not exist: {DOWNLOAD_PATH}")
    except Exception as e:
        print(f"[STARTUP] Error during auto-scan: {e}")
        import traceback
        traceback.print_exc()

# Run auto-scan after all helper functions are defined
auto_scan_on_startup()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
