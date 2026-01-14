# API Documentation

## Overview

This document describes all API endpoints available in the VOD Downloader application.

## Base URL

All endpoints are relative to the Flask application root (typically `http://localhost:5000`).

---

## Main Routes

### `GET /`
**Description**: Main page displaying categories  
**Returns**: HTML page with movie and series categories

---

### `GET /streams?category=<type>:<id>`
**Description**: Get list of movies or series for a category  
**Parameters**:
- `category`: Format `movie:123` or `series:456`

**Returns**: HTML partial with stream items

---

### `GET /episodes/<series_id>`
**Description**: Get all episodes for a series  
**Parameters**:
- `series_id`: Series ID from Xtream API

**Returns**: HTML partial with episode list

---

## Queue Management

### `GET /queue/list`
**Description**: Get list of all queued items  
**Returns**: JSON
```json
{
  "items": [
    {
      "index": 0,
      "id": "uuid",
      "name": "Movie Name",
      "kind": "movie",
      "item_id": "movie:123"
    }
  ],
  "count": 1
}
```

---

### `POST /queue/pause`
**Description**: Pause all downloads  
**Returns**: JSON
```json
{"status": "paused", "message": "Downloads paused"}
```

---

### `POST /queue/resume`
**Description**: Resume paused downloads  
**Returns**: JSON
```json
{"status": "resumed", "message": "Downloads resumed"}
```

---

### `POST /queue/stop`
**Description**: Stop all downloads (interrupts current)  
**Returns**: JSON
```json
{"status": "stopped", "message": "Downloads stopped"}
```

---

### `POST /queue/clear`
**Description**: Clear all pending downloads from queue  
**Returns**: JSON
```json
{"status": "cleared", "message": "Queue cleared"}
```

---

### `DELETE /queue/remove/<job_id>`
**Description**: Remove specific item from queue  
**Parameters**:
- `job_id`: UUID of the job

**Returns**: JSON
```json
{"status": "removed", "message": "Removed: Movie Name"}
```

---

### `POST /queue/reorder`
**Description**: Reorder queue items  
**Body**: JSON
```json
{
  "order": ["job-uuid-1", "job-uuid-2", "job-uuid-3"]
}
```
**Returns**: JSON
```json
{"status": "reordered", "message": "Queue reordered"}
```

---

### `GET /queue/check/<kind>/<id>`
**Description**: Check if item is in queue  
**Parameters**:
- `kind`: `movie` or `series`
- `id`: Item ID

**Returns**: JSON
```json
{"queued": true, "item_id": "movie:123"}
```

---

## Download Tracking

### `GET /queue/downloaded`
**Description**: List all downloaded items  
**Returns**: JSON
```json
{
  "items": {
    "movie:123": {
      "downloaded_at": 1234567890.123,
      "filename": "Movie Name.mp4",
      "size_mb": 1500.5
    }
  },
  "count": 1,
  "db_file": "/path/to/downloaded_items.json",
  "db_exists": true,
  "db_size": 1024
}
```

---

### `GET /queue/db_info`
**Description**: Get database file information  
**Returns**: JSON
```json
{
  "db_file": "/docker/vod-downloader/downloaded_items.json",
  "db_exists": true,
  "db_size": 1024,
  "db_size_kb": 1.0,
  "item_count": 10,
  "download_path": "/downloads",
  "download_path_exists": true
}
```

---

### `POST /queue/mark_downloaded/<kind>/<id>`
**Description**: Manually mark item as downloaded  
**Parameters**:
- `kind`: `movie` or `series`
- `id`: Item ID

**Returns**: JSON
```json
{
  "status": "marked",
  "item_id": "movie:123",
  "filename": "Movie Name.mp4",
  "db_file": "/path/to/downloaded_items.json",
  "message": "Marked movie:123 as downloaded..."
}
```

---

### `POST /queue/mark_all_episodes_downloaded/<series_id>`
**Description**: Mark all episodes in a series as downloaded  
**Parameters**:
- `series_id`: Series ID

**Returns**: JSON
```json
{
  "status": "marked",
  "count": 24,
  "message": "Marked 24 episodes as downloaded"
}
```

---

### `POST /queue/mark_downloaded_batch`
**Description**: Mark multiple items as downloaded  
**Body**: JSON
```json
{
  "item_ids": ["movie:123", "series:456"]
}
```
**Returns**: JSON
```json
{
  "status": "marked",
  "count": 2,
  "message": "Marked 2 items as downloaded"
}
```

---

### `DELETE /queue/downloaded/<item_id>`
**Description**: Remove item from downloaded list  
**Parameters**:
- `item_id`: Format `movie:123` or `series:456`

**Returns**: JSON
```json
{"status": "removed", "message": "Removed movie:123 from downloaded list"}
```

---

### `POST /queue/scan_files`
**Description**: Scan download folder and auto-match files  
**Returns**: JSON
```json
{
  "status": "scanned",
  "files_found": 10,
  "matched": 8,
  "files": [
    {
      "filename": "Movie.mp4",
      "size_mb": 1500.5,
      "matched": true
    }
  ],
  "message": "Scanned 10 files, matched 8 items"
}
```

---

### `POST /queue/scan`
**Description**: Manually trigger database scan  
**Returns**: JSON
```json
{
  "status": "scanned",
  "count": 10,
  "message": "Database contains 10 downloaded items"
}
```

---

## Status

### `GET /status`
**Description**: Get current download status  
**Returns**: HTML partial with progress bar

---

## Queue Actions

### `GET /queue/add/<kind>/<id>/<ext>?title=<title>`
**Description**: Add item to download queue  
**Parameters**:
- `kind`: `movie` or `series`
- `id`: Item ID
- `ext`: File extension (e.g., `mp4`)
- `title`: (optional) Display title

**Returns**: HTML partial with progress bar

---

### `GET /queue/batch_series/<series_id>`
**Description**: Add all episodes of a series to queue  
**Parameters**:
- `series_id`: Series ID

**Returns**: HTML partial with progress bar

---

## Database File Location

The persistent download database is stored at:
```
<app_directory>/downloaded_items.json
```

Where `<app_directory>` is the directory containing `app.py`.

**Example**: If `app.py` is at `/docker/vod-downloader/app.py`, the database will be at `/docker/vod-downloader/downloaded_items.json`

To check the exact location, use the `/queue/db_info` endpoint or check the console output when the app starts.
