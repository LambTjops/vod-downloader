# How to View Application Logs

## Docker Container Logs

If you're running the application in Docker, view logs using:

### View Live Logs (follow mode)
```bash
docker logs -f <container_name>
```

### View Last 100 Lines
```bash
docker logs --tail 100 <container_name>
```

### View Logs with Timestamps
```bash
docker logs -t <container_name>
```

### Find Your Container Name
```bash
docker ps
```
Look for the container running your vod-downloader app.

## Docker Compose Logs

If using docker-compose:

```bash
docker-compose logs -f
```

Or for a specific service:
```bash
docker-compose logs -f vod-downloader
```

## Direct Terminal Output

If running directly with Python (not in Docker):

The logs will appear directly in the terminal where you ran:
```bash
python app.py
```

## What to Look For

### When Scanning Files

Look for log lines starting with `[SCAN]`:
- `[SCAN] Starting file scan...`
- `[SCAN] Step 1: Fetching movie categories...`
- `[SCAN] Step 2: Fetching series categories...`
- `[SCAN] Step 3: Scanning download directory...`
- `[SCAN] ERROR: ...` - Any errors that occur
- `[SCAN] Complete: ...` - Final summary

### When Marking Items as Downloaded

Look for log lines starting with `[DEBUG]`:
- `[DEBUG] mark_downloaded_manual called: ...`
- `[DEBUG] Database file path: ...`
- `[DEBUG] Database file exists before: ...`
- `[DEBUG] mark_item_downloaded returned: ...`

### General Errors

Look for:
- `ERROR:` - General errors
- `FATAL ERROR:` - Critical errors
- Python tracebacks (stack traces)

## Example: Viewing Scan Logs

```bash
# Start following logs
docker logs -f vod-downloader

# Then click "Scan Files" in the UI
# You'll see output like:

[SCAN] Starting file scan...
[SCAN] Step 1: Fetching movie categories...
[SCAN] Found 15 movie categories
[SCAN] Fetching movies from category 1/15: Action
[SCAN] Added 50 movies (total: 50)
...
[SCAN] Step 2: Fetching series categories...
[SCAN] Found 20 series categories
...
[SCAN] ERROR: Error fetching episodes for series XYZ: Connection timeout
...
[SCAN] Complete: Scanned 25 files, matched 18 items
```

## Troubleshooting

### If logs are empty:
1. Check if the container is running: `docker ps`
2. Check if the app is actually logging: Look for any output
3. Try restarting the container

### If you see timeout errors:
- The API provider might be slow
- Too many API calls are being made
- Network issues

### If you see permission errors:
- Check file permissions in the container
- Check if the database directory is writable

## Quick Commands Reference

```bash
# View all logs
docker logs <container_name>

# Follow logs (live updates)
docker logs -f <container_name>

# Last 50 lines
docker logs --tail 50 <container_name>

# Logs with timestamps
docker logs -t <container_name>

# Search logs for specific text
docker logs <container_name> | grep "SCAN"
docker logs <container_name> | grep "ERROR"
```
