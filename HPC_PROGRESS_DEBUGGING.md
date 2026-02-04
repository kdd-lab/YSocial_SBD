# HPC Progress Tracking - Debugging Guide

## Problem
HPC progress bar stuck at 0% even though client has terminated execution.

## Debug Logging Added

Comprehensive debug logging has been added at all key points in the progress tracking flow. This guide explains how to use these logs to diagnose the issue.

## How to Diagnose

### Step 1: Enable Debug Logging

Make sure your Flask application is logging at INFO level or above.

In your Flask config or environment:
```python
import logging
logging.basicConfig(level=logging.INFO)
```

Or set environment variable:
```bash
export FLASK_LOG_LEVEL=INFO
```

### Step 2: Run HPC Experiment

1. Start an HPC experiment from the scheduler or manually
2. Let it run for at least a few simulation steps
3. Open the admin/experiments page (this triggers the polling)

### Step 3: Check Application Logs

Look for log entries in this order:

#### A. Endpoint Call (experiments_routes.py)
```
[INFO] Updating metrics for client 123 (client_test), is_hpc=True, log_file=/path/to/client_test_client.log
```

**What to check:**
- ✅ Is `is_hpc=True` for HPC experiments?
- ✅ Does the log file path look correct?

**If you see:**
```
[WARNING] Log file not found for client 123: /path/to/client_test_client.log
```
→ **Problem**: Log file doesn't exist or path is wrong
→ **Fix**: Check experiment folder, verify HPC client is writing logs

#### B. Function Entry (log_metrics.py)
```
[INFO] update_client_log_metrics called: exp_id=1, client_id=123, is_hpc=True, log_file=/path/to/client_test_client.log
```

**What to check:**
- ✅ Function is being called
- ✅ Parameters are correct

#### C. Log Parsing Summary (log_metrics.py)
```
[INFO] HPC log parsing for client 123: total_lines=500, parsed_lines=450, hourly_summaries=24, daily_summaries=7, max_day=6, max_hour=23
```

**What to check:**
- ✅ Are log lines being read? (`total_lines > 0`)
- ✅ Are lines being parsed? (`parsed_lines > 0`)
- ✅ Are hourly summaries found? (`hourly_summaries > 0`)
- ✅ Are max_day and max_hour being set? (`max_day >= 0`, `max_hour >= 0`)

**Common Issues:**

**Issue 1: No hourly summaries found**
```
hourly_summaries=0, daily_summaries=0, max_day=-1, max_hour=-1
```
→ **Problem**: Log format doesn't match expected HPC format
→ **Expected format**: JSON lines with `"summary_type": "hourly"` or `"summary_type": "daily"`
→ **Fix**: Check actual HPC log file format, update parser if needed

**Issue 2: Lines read but not parsed**
```
total_lines=500, parsed_lines=0
```
→ **Problem**: Log lines are not valid JSON
→ **Fix**: Check log file content, verify JSON format

#### D. Client_Execution Update (log_metrics.py)
```
[INFO] HPC: Updating Client_Execution for client 123 with max_day=6, max_hour=23
[INFO] HPC: Updated Client_Execution for client 123: elapsed_time=168, expected=168
```

**What to check:**
- ✅ Is update being attempted?
- ✅ Are elapsed_time and expected_duration_rounds correct?
- ✅ Progress should be: `elapsed_time / expected * 100`

**If you see:**
```
[WARNING] HPC: Not updating Client_Execution for client 123 because max_day=-1, max_hour=-1
```
→ **Problem**: No hourly summaries were parsed from logs
→ **Root cause**: Log format issue (see Issue 1 above)

**If you see:**
```
[WARNING] HPC: No Client_Execution record found for client 123
```
→ **Problem**: Client_Execution record doesn't exist
→ **Fix**: Should be created when HPC client starts in `start_hpc_client()`

#### E. Frontend Display (experiments_routes.py)
```
[INFO] Client_Execution for client 123: elapsed_time=168, expected=168, last_day=6, last_hour=23
```

**What to check:**
- ✅ Are values non-zero?
- ✅ Is progress being calculated: `elapsed_time / expected * 100`
- ✅ For 7-day experiment: expected should be 168 (7 × 24)

## Common Problem Scenarios

### Scenario 1: Log File Doesn't Exist
**Symptoms:**
```
[WARNING] Log file not found for client 123
```

**Causes:**
- HPC client not started
- HPC client crashed before writing logs
- Wrong log file path/name

**Solutions:**
1. Check if HPC client process is running: `ps aux | grep run_client.py`
2. Check experiment folder: `ls /path/to/experiments/{uid}/`
3. Verify client name matches file name: `{client.name}_client.log`

### Scenario 2: Wrong Log Format
**Symptoms:**
```
[INFO] HPC log parsing: total_lines=500, parsed_lines=450, hourly_summaries=0, daily_summaries=0
```

**Causes:**
- HPC client writing different log format than expected
- Log parser expecting wrong format

**Expected HPC Format:**
```json
{"time": "2024-01-01 10:00:00", "summary_type": "hourly", "day": 0, "slot": 10, "total_execution_time_seconds": 1.23, "actions_by_method": {"post": 5, "follow": 3}}
{"time": "2024-01-01 23:59:59", "summary_type": "daily", "day": 0, "total_execution_time_seconds": 10.5, "actions_by_method": {"post": 100, "follow": 50}}
```

**Solutions:**
1. Check actual log file: `cat /path/to/client_test_client.log | head -20`
2. Verify JSON format
3. Check for `"summary_type": "hourly"` or `"summary_type": "daily"`
4. If format is different, update log parser in `log_metrics.py`

### Scenario 3: Client_Execution Not Created
**Symptoms:**
```
[WARNING] HPC: No Client_Execution record found for client 123
```

**Causes:**
- `start_hpc_client()` not creating record
- Database transaction not committed
- Client started before fix was deployed

**Solutions:**
1. Check database: `SELECT * FROM client_execution WHERE client_id = 123;`
2. Restart HPC client (will trigger creation)
3. Manually create record if needed

### Scenario 4: Progress Calculated But Not Showing
**Symptoms:**
```
[INFO] Client_Execution for client 123: elapsed_time=168, expected=168
```
But frontend still shows 0%

**Causes:**
- Frontend caching
- JavaScript error
- API response not being processed

**Solutions:**
1. Hard refresh browser: Ctrl+Shift+R
2. Check browser console for JavaScript errors
3. Check network tab: verify API returns correct data
4. Verify JSON response has `"progress": 100`

## Verification Steps

After fixing issues, verify the complete flow:

1. **Check logs show progression:**
   ```
   t=0s:   elapsed_time=1   (day 0, hour 0)
   t=30s:  elapsed_time=5   (day 0, hour 4)
   t=60s:  elapsed_time=10  (day 0, hour 9)
   ...
   ```

2. **Check database updates:**
   ```sql
   SELECT elapsed_time, last_active_day, last_active_hour, expected_duration_rounds
   FROM client_execution
   WHERE client_id = 123
   ORDER BY id DESC LIMIT 1;
   ```

3. **Check frontend updates:**
   - Open admin/experiments page
   - Watch progress bar increase every 30 seconds
   - Verify percentage matches: `(elapsed / expected) * 100`

## Quick Diagnostic Script

Run this to check current state:

```bash
# Check if HPC client process running
ps aux | grep run_client.py

# Check if log file exists and has content
ls -lh /path/to/experiments/*/client_*_client.log
tail -20 /path/to/experiments/*/client_*_client.log

# Check database state
sqlite3 /path/to/database_server.db "SELECT * FROM client_execution;"

# Check application logs (last 100 lines with HPC keywords)
tail -100 /path/to/application.log | grep -i "hpc\|client_execution\|elapsed_time"
```

## Next Steps

After identifying the root cause:
1. Implement the appropriate fix
2. Test with a fresh HPC experiment
3. Monitor logs to verify fix works
4. Remove or reduce debug logging once issue is resolved

## Need More Help?

If logs don't reveal the issue, add even more detailed logging:
- Log every JSON line parsed
- Log the actual log file content
- Log database queries and results
- Enable Flask debug mode for full stack traces
