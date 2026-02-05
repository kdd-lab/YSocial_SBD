# Automatic Log Sync for HPC Experiments

## Overview
YSocial includes an automatic background service that periodically syncs logs from running experiments and updates progress tracking in the database. This is especially important for HPC experiments where Client_Execution records must be updated to track progress and detect completion.

## How It Works

### Background Scheduler
- **Service**: `LogSyncScheduler` 
- **Thread**: Runs as a daemon thread (background)
- **Auto-start**: Automatically starts when the application launches
- **Configurable**: Users can enable/disable and set sync interval

### What Gets Synced
For all running experiments (`running=1`):
1. **Server logs**: `_server.log` files
2. **Client logs**: `{client_name}_client.log` files for running clients

For HPC experiments specifically:
- Updates `Client_Execution` table with:
  - `elapsed_time`: Current simulation round
  - `last_active_day`: Latest day in logs
  - `last_active_hour`: Latest hour in logs
- Detects completion when `elapsed_time >= expected_duration_rounds`
- Auto-stops clients and server when all clients complete
- Updates experiment status to "completed"
- Enables scheduler to progress to next experiments

## Configuration

### Via Web UI
1. Navigate to `/admin/miscellanea`
2. Find "Automatic Log Synchronization" section
3. Configure:
   - **Enable/Disable**: Toggle automatic sync
   - **Sync Interval**: 1-1440 minutes (default: 10)
   - **Manual Sync**: Click "Sync Now" for immediate sync

### Default Settings
- **Enabled**: Yes (True)
- **Interval**: 10 minutes
- **Created**: Automatically on first access

### Database
Settings are stored in `LogSyncSettings` table:
```sql
SELECT * FROM log_sync_settings;
```

## Verification

### Check Scheduler Status
The scheduler starts automatically. Check application logs for:
```
✓ Log sync scheduler started
```

### Check Sync Activity
When syncs occur, you'll see in logs:
```
Starting automatic log sync...
Synced HPC client logs for client_name in experiment exp_name
Automatic log sync completed
```

### Check Client_Execution Updates
For an HPC experiment with running clients, check if records update:
```sql
SELECT 
    client_id,
    elapsed_time,
    last_active_day,
    last_active_hour,
    expected_duration_rounds
FROM client_execution
WHERE client_id IN (
    SELECT id FROM client WHERE id_exp = <your_exp_id>
);
```

You should see `elapsed_time`, `last_active_day`, and `last_active_hour` increasing over time.

## Troubleshooting

### Issue: Client_Execution Not Updating

#### Check 1: Is sync enabled?
```sql
SELECT enabled, sync_interval_minutes, last_sync 
FROM log_sync_settings;
```
- `enabled` should be `1` (True)
- Check `last_sync` timestamp - should update regularly

#### Check 2: Is experiment marked as running?
```sql
SELECT idexp, exp_name, running, simulator_type
FROM exps
WHERE idexp = <your_exp_id>;
```
- `running` should be `1`
- `simulator_type` should be `"HPC"`

#### Check 3: Are clients marked as running?
```sql
SELECT id, name, status, id_exp
FROM client
WHERE id_exp = <your_exp_id>;
```
- `status` should be `1` for running clients

#### Check 4: Do log files exist?
Check if log files exist in experiment folder:
```bash
ls -la y_web/experiments/<exp_uid>/*_client.log
```

### Issue: Sync Interval Too Long

If 10 minutes feels too slow, you can:
1. Go to `/admin/miscellanea`
2. Change "Sync Interval" to a lower value (e.g., 1-5 minutes)
3. Click "Save Settings"

The scheduler checks every 60 seconds, so changes take effect within 1 minute.

### Issue: Need Immediate Update

Instead of waiting for automatic sync:
1. Go to `/admin/miscellanea`
2. Click "Sync Now" button
3. Or visit the experiment details page (triggers manual sync)

## Performance Considerations

### Sync Interval Guidelines
- **1-2 minutes**: Fast updates, higher system load
- **5-10 minutes**: Balanced (recommended)
- **15-30 minutes**: Lower load, slower updates

### System Load
Each sync:
- Reads log files (only new entries since last sync)
- Updates database records
- For large experiments (many clients), use longer intervals

### Best Practices
- Use shorter intervals (1-5 min) for active development/testing
- Use longer intervals (10-30 min) for production with many experiments
- Disable sync if not needed to save resources

## Integration with Scheduler

The automatic log sync is critical for the experiment scheduler:

1. **Progress Tracking**: Updates Client_Execution records
2. **Completion Detection**: Identifies when clients finish
3. **Auto-Stop**: Stops completed experiments automatically
4. **Scheduler Progression**: Enables moving to next experiment group

Without automatic sync, the scheduler would not detect experiment completion and would appear "stuck".

## Manual Sync Triggers

Automatic sync runs in background, but you can also trigger manually:

1. **Web UI**: "Sync Now" button in `/admin/miscellanea`
2. **Experiment Details**: Visiting `/admin/experiment_details/<exp_id>` triggers sync
3. **API**: `POST /admin/trigger_log_sync`

## Logs

### Application Logs
Monitor application logs for sync activity:
```
[INFO] Starting automatic log sync...
[INFO] Synced HPC client logs for client_test in experiment exp_hpc
[INFO] Automatic log sync completed
```

### Log Levels
- `INFO`: Major sync events (start, HPC client updates, completion)
- `DEBUG`: Individual client syncs (Standard experiments)
- `WARNING`: Errors during sync (non-fatal)
- `ERROR`: Critical failures

## Summary

The automatic log sync service:
- ✅ **Runs automatically** in background
- ✅ **User configurable** via web UI
- ✅ **Essential for HPC experiments** to track progress
- ✅ **Enables scheduler** to detect completion
- ✅ **No manual intervention** required

For HPC experiments started via scheduler, this service ensures Client_Execution records are properly updated, progress is tracked, and experiments complete successfully!
