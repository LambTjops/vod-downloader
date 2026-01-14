# VOD Downloader

A modern web-based Video-On-Demand (VOD) downloader for Xtream Codes API providers. Features a beautiful, responsive UI with comprehensive queue management, download tracking, and persistent state management.

## Features

### Core Functionality
- **Browse Movies & Series**: Browse and search through available VOD content from your Xtream provider
- **Queue Management**: Add items to download queue with full control
- **Download Tracking**: Persistent tracking of downloaded items (survives restarts and file moves)
- **Batch Operations**: Download entire series at once or mark all episodes as downloaded

### Queue Management
- **Pause/Resume**: Pause downloads without losing progress
- **Stop**: Stop all downloads (interrupts current download)
- **Remove Items**: Remove individual items from queue
- **Reorder**: Drag items up/down to change download order
- **Clear Queue**: Clear all pending downloads
- **Real-time Updates**: Auto-refreshing queue status

### Download Tracking
- **Persistent Storage**: Downloads tracked in `downloaded_items.json`
- **Duplicate Prevention**: Prevents re-downloading already downloaded items
- **Manual Marking**: Mark items as downloaded manually
- **Auto-scan**: Scan download folder and auto-match files
- **Status Indicators**: Visual indicators for downloaded/queued/available items

### User Interface
- **Modern Design**: Dark theme with gradient accents
- **Responsive Layout**: Works on desktop and mobile
- **Search & Filters**: Search episodes, filter by season/status
- **Sticky Headers**: Important controls always accessible
- **Visual Feedback**: Clear status indicators and progress bars

## Configuration

Set the following environment variables:

```bash
XC_URL=http://your-provider-url.com:8080
XC_USER=your_username
XC_PASS=your_password
```

Or edit them directly in `app.py`:

```python
XC_URL = os.getenv("XC_URL", "http://provider-url.com:8080")
XC_USER = os.getenv("XC_USER", "username")
XC_PASS = os.getenv("XC_PASS", "password")
DOWNLOAD_PATH = "/downloads"  # Change this to your download directory
```

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
python app.py
```

3. Access the web interface:
```
http://localhost:5000
```

## Docker

Build and run with Docker:

```bash
docker build -t vod-downloader .
docker run -p 5000:5000 \
  -e XC_URL=http://your-provider-url.com:8080 \
  -e XC_USER=your_username \
  -e XC_PASS=your_password \
  -v /path/to/downloads:/downloads \
  -v /path/to/app/data:/app \
  vod-downloader
```

## File Structure

```
vod-downloader/
├── app.py                      # Main application file
├── downloaded_items.json       # Persistent download database (created automatically)
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker configuration
├── README.md                   # This file
└── templates/
    ├── index.html             # Main page
    ├── streams_partial.html  # Movies/series list
    ├── episodes_partial.html  # Episodes list
    ├── queue_manager.html     # Queue management UI
    └── progress_bar.html      # Download progress indicator
```

## Persistent Download Database

The application stores downloaded items in `downloaded_items.json` located in the same directory as `app.py`.

**Location**: `/docker/vod-downloader/downloaded_items.json` (or wherever you run the app)

**Format**:
```json
{
  "movie:12345": {
    "downloaded_at": 1234567890.123,
    "filename": "Movie Name.mp4",
    "size_mb": 1500.5
  },
  "series:67890": {
    "downloaded_at": 1234567891.456,
    "filename": "Series Name - S01E01 - Episode Title.mp4",
    "size_mb": 800.2
  }
}
```

**Features**:
- Persists across application restarts
- Works even if files are moved or deleted
- Tracks by item ID, not file path
- Stores metadata (download time, filename, size)

## API Endpoints

### Queue Management
- `GET /queue/list` - Get all queued items
- `POST /queue/pause` - Pause all downloads
- `POST /queue/resume` - Resume downloads
- `POST /queue/stop` - Stop all downloads
- `POST /queue/clear` - Clear queue
- `DELETE /queue/remove/<job_id>` - Remove specific item
- `POST /queue/reorder` - Reorder queue items

### Download Tracking
- `GET /queue/downloaded` - List all downloaded items
- `POST /queue/mark_downloaded/<kind>/<id>` - Mark item as downloaded
- `POST /queue/mark_all_episodes_downloaded/<series_id>` - Mark all episodes
- `POST /queue/scan_files` - Scan and auto-match files
- `DELETE /queue/downloaded/<item_id>` - Remove from downloaded list

### Status
- `GET /status` - Get current download status

## Troubleshooting

### Database File Not Found
The database file `downloaded_items.json` is created automatically in the same directory as `app.py`. Check:
1. Application has write permissions in the directory
2. Check console output for the exact file path
3. File is created on first mark/download operation

### Downloads Not Tracking
1. Check console logs for errors
2. Verify `downloaded_items.json` exists and is writable
3. Check file permissions on the download directory

### Queue Not Working
1. Check browser console for JavaScript errors
2. Verify Flask app is running
3. Check network tab for API errors

## Development

### Code Structure
- **app.py**: Main Flask application with routes and business logic
- **templates/**: Jinja2 HTML templates
- **Background Worker**: Thread-based download worker with pause/resume support
- **Queue System**: Thread-safe deque-based queue with management features

### Key Components
- `JOB_QUEUE`: Thread-safe queue of download jobs
- `DOWNLOADED_ITEMS`: Persistent dictionary of downloaded items
- `QUEUED_ITEMS`: Set tracking items currently in queue
- `DOWNLOAD_STATE`: Current download progress and status

## License

This project is provided as-is for personal use.
