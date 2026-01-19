"""
Utility functions for incremental log reading and metric aggregation.

This module provides functionality to:
- Track file offsets for incremental reading
- Parse log files and extract metrics
- Aggregate metrics in database tables
"""

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import and_
from sqlalchemy.exc import OperationalError, PendingRollbackError

from y_web import db
from y_web.models import (
    Client,
    Client_Execution,
    ClientLogMetrics,
    LogFileOffset,
    ServerLogMetrics,
)

# Set up logger
logger = logging.getLogger(__name__)

# Retry configuration for database deadlocks
MAX_RETRIES = 3
RETRY_DELAY = 0.5  # seconds

# Base time for HPC simulation time calculations
# Used to create synthetic timestamps where (max_time - min_time) = simulation_time_seconds
HPC_BASE_TIME = datetime(2000, 1, 1, 0, 0, 0)


def _ensure_session_clean(session):
    """
    Ensure the database session is in a clean state.

    This is needed to handle PendingRollbackError which can occur
    when a previous database operation failed.
    """
    try:
        # Check if session needs rollback
        if session.is_active:
            session.rollback()
    except Exception as e:
        logger.debug(f"Session cleanup exception (can be safely ignored): {e}")


def _commit_with_retry(session, max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """
    Commit a database session with retry logic for deadlock handling.

    Args:
        session: SQLAlchemy session to commit
        max_retries: Maximum number of retry attempts
        delay: Delay between retries in seconds

    Returns:
        bool: True if commit succeeded, False otherwise
    """
    for attempt in range(max_retries):
        try:
            session.commit()
            return True
        except PendingRollbackError:
            # Session was in bad state, rollback and retry
            session.rollback()
            if attempt < max_retries - 1:
                logger.warning(
                    f"Session rollback needed, retrying ({attempt + 1}/{max_retries})..."
                )
                time.sleep(delay * (attempt + 1))
            else:
                logger.error(f"Session rollback persisted after {max_retries} retries")
                return False
        except OperationalError as e:
            session.rollback()
            error_msg = str(e).lower()
            if "deadlock" in error_msg or "lock" in error_msg:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Database deadlock detected, retrying ({attempt + 1}/{max_retries})..."
                    )
                    time.sleep(delay * (attempt + 1))  # Exponential backoff
                else:
                    logger.error(
                        f"Database deadlock persisted after {max_retries} retries"
                    )
                    return False
            else:
                logger.error(f"Database error during commit: {e}")
                return False
        except Exception as e:
            session.rollback()
            logger.error(f"Unexpected error during commit: {e}")
            return False
    return False


def get_log_file_offset(exp_id, log_file_type, file_path, client_id=None):
    """
    Get the last read offset for a log file.

    Args:
        exp_id: Experiment ID
        log_file_type: Type of log file ('server' or 'client')
        file_path: Relative path to the log file
        client_id: Client ID (only for client logs)

    Returns:
        int: Last read offset in bytes (0 if not found)
    """
    offset_record = LogFileOffset.query.filter_by(
        exp_id=exp_id,
        log_file_type=log_file_type,
        file_path=file_path,
        client_id=client_id,
    ).first()

    if offset_record:
        return offset_record.last_offset
    return 0


def update_log_file_offset(
    exp_id, log_file_type, file_path, new_offset, client_id=None
):
    """
    Update the last read offset for a log file.

    Args:
        exp_id: Experiment ID
        log_file_type: Type of log file ('server' or 'client')
        file_path: Relative path to the log file
        new_offset: New offset in bytes
        client_id: Client ID (only for client logs)
    """
    offset_record = LogFileOffset.query.filter_by(
        exp_id=exp_id,
        log_file_type=log_file_type,
        file_path=file_path,
        client_id=client_id,
    ).first()

    if offset_record:
        offset_record.last_offset = new_offset
        offset_record.last_updated = datetime.utcnow()
    else:
        offset_record = LogFileOffset(
            exp_id=exp_id,
            log_file_type=log_file_type,
            file_path=file_path,
            last_offset=new_offset,
            client_id=client_id,
            last_updated=datetime.utcnow(),
        )
        db.session.add(offset_record)

    _commit_with_retry(db.session)


def reset_hpc_client_metrics(exp_id, client_id):
    """
    Reset client metrics and file offsets for an HPC experiment.

    This is needed when switching to a new log format or to force re-parsing.
    Only affects the specific client, not the entire experiment.

    Args:
        exp_id: Experiment ID
        client_id: Client ID to reset
    """
    try:
        # Delete existing client metrics
        ClientLogMetrics.query.filter_by(exp_id=exp_id, client_id=client_id).delete()

        # Delete file offsets for this client
        LogFileOffset.query.filter_by(
            exp_id=exp_id, log_file_type="client", client_id=client_id
        ).delete()

        success = _commit_with_retry(db.session)
        if success:
            logger.info(
                f"Reset client metrics and offsets for exp_id={exp_id}, client_id={client_id}"
            )
        return success
    except Exception as e:
        logger.error(f"Error resetting client metrics: {e}", exc_info=True)
        # Don't call rollback here - _commit_with_retry already handles it
        return False


def reset_hpc_server_metrics(exp_id):
    """
    Reset server metrics and file offsets for an HPC experiment.

    This is needed when switching to a new log format or to force re-parsing.

    Args:
        exp_id: Experiment ID
    """
    try:
        # Delete existing server metrics
        ServerLogMetrics.query.filter_by(exp_id=exp_id).delete()

        # Delete file offsets for server logs
        LogFileOffset.query.filter_by(exp_id=exp_id, log_file_type="server").delete()

        success = _commit_with_retry(db.session)
        if success:
            logger.info(f"Reset server metrics and offsets for exp_id={exp_id}")
        return success
    except Exception as e:
        logger.error(f"Error resetting server metrics: {e}", exc_info=True)
        # Don't call rollback here - _commit_with_retry already handles it
        return False


def parse_server_log_incremental(log_file_path, exp_id, start_offset=0, is_hpc=False):
    """
    Parse server log file incrementally from a given offset.

    Args:
        log_file_path: Full path to the server log file
        exp_id: Experiment ID
        start_offset: Byte offset to start reading from
        is_hpc: Boolean flag indicating if this is an HPC experiment (uses different log format)

    Returns:
        tuple: (new_offset, metrics_dict)
            - new_offset: New byte offset after reading
            - metrics_dict: Dictionary with aggregated metrics
    """
    if not os.path.exists(log_file_path):
        return start_offset, {}

    # Data structures for aggregation
    daily_data = defaultdict(
        lambda: defaultdict(
            lambda: {"count": 0, "duration": 0.0, "times": [], "simulation_time": 0.0}
        )
    )
    hourly_data = defaultdict(
        lambda: defaultdict(
            lambda: {"count": 0, "duration": 0.0, "times": [], "simulation_time": 0.0}
        )
    )

    try:
        with open(log_file_path, "r") as f:
            # Seek to the start offset
            f.seek(start_offset)

            line_count = 0
            parsed_count = 0
            hpc_summary_count = 0
            hpc_daily_count = 0
            hpc_hourly_count = 0
            errors = []

            for line in f:
                line_count += 1
                line = line.strip()
                if not line:
                    continue

                try:
                    # Parse JSON - log entries should already be properly formatted
                    log_entry = json.loads(line)
                    parsed_count += 1

                    if is_hpc:
                        # HPC format: use summary entries (hourly and daily)
                        # Format: {"time": "2026-01-19 10:02:22", "summary_type": "hourly", "day": 1, "slot": 15,
                        #          "total_actions": 4, "successful_actions": 4, 
                        #          "total_execution_time_seconds": 1.0336, "average_execution_time_seconds": 0.2584,
                        #          "actions_by_method": {"like": 2, "laugh": 1, "follow": 1}}
                        summary_type = log_entry.get("summary_type")
                        if summary_type not in ("hourly", "daily"):
                            if line_count <= 5:  # Log first few skipped entries
                                errors.append(f"Line {line_count}: No summary_type or wrong type: {summary_type}")
                            continue
                        
                        hpc_summary_count += 1

                        day = log_entry.get("day")
                        if day is None:
                            errors.append(f"Line {line_count}: Missing day field")
                            continue  # Skip entries without a valid day

                        # Parse timestamp if available for time tracking
                        time_str = log_entry.get("time", "")
                        time_obj = None
                        if time_str:
                            try:
                                time_obj = datetime.strptime(
                                    time_str, "%Y-%m-%d %H:%M:%S"
                                )
                            except ValueError:
                                pass

                        # For HPC, we use total_execution_time_seconds for both compute and simulation time
                        # as per the actual log format
                        total_execution_time = float(
                            log_entry.get("total_execution_time_seconds", 0)
                        )
                        path = "all"  # Aggregate all paths for HPC

                        # For daily summaries
                        # HPC summaries contain absolute values, not deltas
                        if summary_type == "daily":
                            hpc_daily_count += 1
                            daily_data[day][path]["count"] = 1
                            daily_data[day][path]["duration"] = total_execution_time
                            daily_data[day][path]["simulation_time"] = total_execution_time
                            if time_obj:
                                daily_data[day][path]["times"].append(time_obj)

                        # For hourly summaries
                        elif summary_type == "hourly":
                            hour = log_entry.get("slot")  # HPC uses "slot" for hour
                            if hour is not None:
                                hpc_hourly_count += 1
                                key = f"{day}-{hour}"
                                hourly_data[key][path]["count"] = 1
                                hourly_data[key][path]["duration"] = total_execution_time
                                hourly_data[key][path][
                                    "simulation_time"
                                ] = total_execution_time
                                if time_obj:
                                    hourly_data[key][path]["times"].append(time_obj)
                            else:
                                errors.append(f"Line {line_count}: Hourly entry missing slot field")
                    else:
                        # Standard format: individual log entries per request
                        path = log_entry.get("path", "unknown")
                        duration = float(log_entry.get("duration", 0))
                        day = log_entry.get("day")
                        hour = log_entry.get("hour")
                        time_str = log_entry.get("time", "")

                        # Parse timestamp if available
                        time_obj = None
                        if time_str:
                            try:
                                time_obj = datetime.strptime(
                                    time_str, "%Y-%m-%d %H:%M:%S"
                                )
                            except ValueError:
                                pass

                        # Aggregate by day
                        if day is not None:
                            daily_data[day][path]["count"] += 1
                            daily_data[day][path]["duration"] += duration
                            if time_obj:
                                daily_data[day][path]["times"].append(time_obj)

                        # Aggregate by day-hour
                        if day is not None and hour is not None:
                            key = f"{day}-{hour}"
                            hourly_data[key][path]["count"] += 1
                            hourly_data[key][path]["duration"] += duration
                            if time_obj:
                                hourly_data[key][path]["times"].append(time_obj)

                except json.JSONDecodeError as e:
                    # Skip invalid JSON lines
                    if line_count <= 5:
                        errors.append(f"Line {line_count}: JSON decode error: {str(e)[:100]}")
                    continue

            # Get the new offset
            new_offset = f.tell()
            
            # Print debug info for HPC experiments
            if is_hpc:
                print(f"\n=== HPC Log Parsing Debug ({log_file_path}) ===")
                print(f"Total lines read: {line_count}")
                print(f"Successfully parsed JSON: {parsed_count}")
                print(f"HPC summary entries found: {hpc_summary_count}")
                print(f"Daily entries processed: {hpc_daily_count}")
                print(f"Hourly entries processed: {hpc_hourly_count}")
                print(f"Daily data keys: {list(daily_data.keys())}")
                print(f"Hourly data keys: {list(hourly_data.keys())[:10]}")
                if errors:
                    print(f"Errors (first 10): {errors[:10]}")
                print("==========================================\n")

    except Exception as e:
        logger.error(f"Error reading server log file: {e}", exc_info=True)
        print(f"CRITICAL ERROR reading log file: {e}")
        return start_offset, {}

    # Update database with new metrics
    for day, paths in daily_data.items():
        for path, data in paths.items():
            # For HPC with simulation_time, create synthetic timestamps
            # so that (max_time - min_time) = simulation_time
            if is_hpc and data["simulation_time"] > 0:
                # Create cumulative timeline: each day starts where previous day ended
                # Day 0 starts at base time, day 1 starts at base + 1 day of sim time, etc.
                day_start = HPC_BASE_TIME + timedelta(days=day)
                min_time = day_start
                max_time = day_start + timedelta(seconds=data["simulation_time"])
            else:
                # For standard experiments, use actual timestamps
                min_time = min(data["times"]) if data["times"] else None
                max_time = max(data["times"]) if data["times"] else None

            # Check if record exists
            metric = ServerLogMetrics.query.filter_by(
                exp_id=exp_id, aggregation_level="daily", day=day, hour=None, path=path
            ).first()

            if metric:
                # Update existing record
                # For HPC, values are absolute (replace); for standard, they're deltas (accumulate)
                if is_hpc:
                    metric.call_count = data["count"]
                    metric.total_duration = data["duration"]
                else:
                    metric.call_count += data["count"]
                    metric.total_duration += data["duration"]
                if min_time and (not metric.min_time or min_time < metric.min_time):
                    metric.min_time = min_time
                if max_time and (not metric.max_time or max_time > metric.max_time):
                    metric.max_time = max_time
            else:
                # Create new record
                metric = ServerLogMetrics(
                    exp_id=exp_id,
                    aggregation_level="daily",
                    day=day,
                    hour=None,
                    path=path,
                    call_count=data["count"],
                    total_duration=data["duration"],
                    min_time=min_time,
                    max_time=max_time,
                )
                db.session.add(metric)

    for key, paths in hourly_data.items():
        day, hour = key.split("-")
        day = int(day)
        hour = int(hour)

        for path, data in paths.items():
            # For HPC with simulation_time, create synthetic timestamps
            if is_hpc and data["simulation_time"] > 0:
                # Create cumulative timeline: each hour starts where previous hour ended
                # Hour offset within the simulation
                hour_offset = day * 24 + hour
                hour_start = HPC_BASE_TIME + timedelta(hours=hour_offset)
                min_time = hour_start
                max_time = hour_start + timedelta(seconds=data["simulation_time"])
            else:
                # For standard experiments, use actual timestamps
                min_time = min(data["times"]) if data["times"] else None
                max_time = max(data["times"]) if data["times"] else None

            # Check if record exists
            metric = ServerLogMetrics.query.filter_by(
                exp_id=exp_id, aggregation_level="hourly", day=day, hour=hour, path=path
            ).first()

            if metric:
                # Update existing record
                # For HPC, values are absolute (replace); for standard, they're deltas (accumulate)
                if is_hpc:
                    metric.call_count = data["count"]
                    metric.total_duration = data["duration"]
                else:
                    metric.call_count += data["count"]
                    metric.total_duration += data["duration"]
                if min_time and (not metric.min_time or min_time < metric.min_time):
                    metric.min_time = min_time
                if max_time and (not metric.max_time or max_time > metric.max_time):
                    metric.max_time = max_time
            else:
                # Create new record
                metric = ServerLogMetrics(
                    exp_id=exp_id,
                    aggregation_level="hourly",
                    day=day,
                    hour=hour,
                    path=path,
                    call_count=data["count"],
                    total_duration=data["duration"],
                    min_time=min_time,
                    max_time=max_time,
                )
                db.session.add(metric)

    _commit_with_retry(db.session)

    return new_offset, {"daily": daily_data, "hourly": hourly_data}


def parse_client_log_incremental(
    log_file_path, exp_id, client_id, start_offset=0, is_hpc=False
):
    """
    Parse client log file incrementally from a given offset.

    Args:
        log_file_path: Full path to the client log file
        exp_id: Experiment ID
        client_id: Client ID
        start_offset: Byte offset to start reading from
        is_hpc: Boolean flag indicating if this is an HPC experiment (uses different log format)

    Returns:
        tuple: (new_offset, metrics_dict)
            - new_offset: New byte offset after reading
            - metrics_dict: Dictionary with aggregated metrics
    """
    if not os.path.exists(log_file_path):
        return start_offset, {}

    # Data structures for aggregation
    daily_data = defaultdict(
        lambda: defaultdict(lambda: {"count": 0, "execution_time": 0.0})
    )
    hourly_data = defaultdict(
        lambda: defaultdict(lambda: {"count": 0, "execution_time": 0.0})
    )

    # Track max day/hour for HPC client_execution updates
    max_day = -1
    max_hour = -1

    try:
        with open(log_file_path, "r") as f:
            # Seek to the start offset
            f.seek(start_offset)

            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    log_entry = json.loads(line)

                    if is_hpc:
                        # HPC format: use summary entries (hourly and daily)
                        # Format: {"time": "...", "summary_type": "hourly", "day": 1, "slot": 8,
                        #          "total_execution_time_seconds": 0.0246,
                        #          "actions_by_method": {"follow": 1, "post": 2}}
                        summary_type = log_entry.get("summary_type")
                        if summary_type not in ("hourly", "daily"):
                            continue

                        day = log_entry.get("day")
                        if day is None:
                            continue  # Skip entries without a valid day

                        total_execution_time = float(
                            log_entry.get("total_execution_time_seconds", 0)
                        )
                        actions_by_method = log_entry.get("actions_by_method", {})

                        # Calculate time per action once for proportional distribution
                        total_actions = (
                            sum(actions_by_method.values()) if actions_by_method else 0
                        )
                        time_per_action = (
                            (total_execution_time / total_actions)
                            if total_actions > 0
                            else 0
                        )

                        # For hourly summaries, get slot (hour) once before loop
                        hour = (
                            log_entry.get("slot") if summary_type == "hourly" else None
                        )

                        # Track max day/hour for client_execution updates
                        if summary_type == "hourly" and hour is not None:
                            if day > max_day or (day == max_day and hour > max_hour):
                                max_day = day
                                max_hour = hour

                        # Process each action method
                        for method_name, count in actions_by_method.items():
                            # Calculate proportional execution time for this method
                            method_time = time_per_action * count

                            # For daily summaries, aggregate by day
                            # HPC summaries contain absolute values, not deltas
                            if summary_type == "daily":
                                daily_data[day][method_name]["count"] = count
                                daily_data[day][method_name][
                                    "execution_time"
                                ] = method_time

                            # For hourly summaries, aggregate by day-hour
                            elif summary_type == "hourly" and hour is not None:
                                key = f"{day}-{hour}"
                                hourly_data[key][method_name]["count"] = count
                                hourly_data[key][method_name][
                                    "execution_time"
                                ] = method_time
                    else:
                        # Standard format: individual log entries per method call
                        method_name = log_entry.get("method_name", "unknown")
                        execution_time = float(
                            log_entry.get("execution_time_seconds", 0)
                        )
                        day = log_entry.get("day")
                        hour = log_entry.get("hour")

                        # Aggregate by day
                        if day is not None:
                            daily_data[day][method_name]["count"] += 1
                            daily_data[day][method_name][
                                "execution_time"
                            ] += execution_time

                        # Aggregate by day-hour
                        if day is not None and hour is not None:
                            key = f"{day}-{hour}"
                            hourly_data[key][method_name]["count"] += 1
                            hourly_data[key][method_name][
                                "execution_time"
                            ] += execution_time

                except json.JSONDecodeError:
                    # Skip invalid JSON lines
                    continue

            # Get the new offset
            new_offset = f.tell()

    except Exception as e:
        logger.error(f"Error reading client log file: {e}", exc_info=True)
        return start_offset, {}

    # Update database with new metrics
    for day, methods in daily_data.items():
        for method_name, data in methods.items():
            # Check if record exists
            metric = ClientLogMetrics.query.filter_by(
                exp_id=exp_id,
                client_id=client_id,
                aggregation_level="daily",
                day=day,
                hour=None,
                method_name=method_name,
            ).first()

            if metric:
                # Update existing record
                # For HPC, values are absolute (replace); for standard, they're deltas (accumulate)
                if is_hpc:
                    metric.call_count = data["count"]
                    metric.total_execution_time = data["execution_time"]
                else:
                    metric.call_count += data["count"]
                    metric.total_execution_time += data["execution_time"]
            else:
                # Create new record
                metric = ClientLogMetrics(
                    exp_id=exp_id,
                    client_id=client_id,
                    aggregation_level="daily",
                    day=day,
                    hour=None,
                    method_name=method_name,
                    call_count=data["count"],
                    total_execution_time=data["execution_time"],
                )
                db.session.add(metric)

    for key, methods in hourly_data.items():
        day, hour = key.split("-")
        day = int(day)
        hour = int(hour)

        for method_name, data in methods.items():
            # Check if record exists
            metric = ClientLogMetrics.query.filter_by(
                exp_id=exp_id,
                client_id=client_id,
                aggregation_level="hourly",
                day=day,
                hour=hour,
                method_name=method_name,
            ).first()

            if metric:
                # Update existing record
                # For HPC, values are absolute (replace); for standard, they're deltas (accumulate)
                if is_hpc:
                    metric.call_count = data["count"]
                    metric.total_execution_time = data["execution_time"]
                else:
                    metric.call_count += data["count"]
                    metric.total_execution_time += data["execution_time"]
            else:
                # Create new record
                metric = ClientLogMetrics(
                    exp_id=exp_id,
                    client_id=client_id,
                    aggregation_level="hourly",
                    day=day,
                    hour=hour,
                    method_name=method_name,
                    call_count=data["count"],
                    total_execution_time=data["execution_time"],
                )
                db.session.add(metric)

    _commit_with_retry(db.session)

    # For HPC, update Client_Execution with progress information
    if is_hpc and max_day >= 0 and max_hour >= 0:
        try:
            client_exec = Client_Execution.query.filter_by(client_id=client_id).first()
            if client_exec:
                # Update last active day and hour
                client_exec.last_active_day = max_day
                client_exec.last_active_hour = max_hour

                # Update elapsed_time (current round, 1-indexed)
                # day 0, hour 0 = round 1
                client_exec.elapsed_time = max_day * 24 + max_hour + 1

                # Check if simulation is complete
                current_round = client_exec.elapsed_time
                if current_round >= client_exec.expected_duration_rounds:
                    # Get the client and mark as stopped
                    client = Client.query.filter_by(id=client_id).first()
                    if client and client.status == 1:
                        client.status = 0
                        logger.info(
                            f"HPC client {client_id} simulation complete at round {current_round}, marking as stopped"
                        )

                _commit_with_retry(db.session)
        except Exception as e:
            logger.error(
                f"Error updating client_execution for HPC client {client_id}: {e}",
                exc_info=True,
            )

    return new_offset, {
        "daily": daily_data,
        "hourly": hourly_data,
        "max_day": max_day,
        "max_hour": max_hour,
    }


def get_rotating_log_files(base_log_path):
    """
    Get all rotating log files for a given base log path.

    Rotating logs are named like: _server.log, _server.log.1, _server.log.2, etc.
    Higher numbers are older files. We return them sorted oldest to newest
    so they are processed in chronological order.

    Args:
        base_log_path: Full path to the main log file (e.g., /path/to/_server.log)

    Returns:
        list: List of log file paths sorted oldest to newest
    """
    log_files = []
    log_dir = os.path.dirname(base_log_path)
    base_name = os.path.basename(base_log_path)

    if not os.path.exists(log_dir):
        return log_files

    # Find all rotating log files
    for filename in os.listdir(log_dir):
        if filename == base_name:
            # Main log file (newest)
            log_files.append((0, os.path.join(log_dir, filename)))
        elif filename.startswith(base_name + "."):
            # Rotating log file (e.g., _server.log.1, _server.log.2)
            try:
                suffix = filename[len(base_name) + 1 :]
                if suffix.isdigit():
                    log_files.append((int(suffix), os.path.join(log_dir, filename)))
            except (ValueError, IndexError):
                pass

    # Sort by suffix number descending (highest = oldest first)
    # This ensures we process logs in chronological order (oldest to newest)
    log_files.sort(key=lambda x: x[0], reverse=True)

    return [path for _, path in log_files]


def has_server_log_files(base_log_path):
    """
    Check if any server log files exist (main or rotated).

    Args:
        base_log_path: Full path to the main log file (e.g., /path/to/_server.log)

    Returns:
        bool: True if any log files exist, False otherwise
    """
    return len(get_rotating_log_files(base_log_path)) > 0


def update_server_log_metrics(exp_id, log_file_path, is_hpc=False):
    """
    Update server log metrics by reading new log entries.

    Only processes the main log file (_server.log) for incremental updates.
    Rotated log files (.log.1, .log.2, etc.) are skipped because their content
    was already processed when they were the main log file.

    Args:
        exp_id: Experiment ID
        log_file_path: Full path to the main server log file
        is_hpc: Boolean flag indicating if this is an HPC experiment (uses different log format)

    Returns:
        bool: True if successful, False otherwise
    """
    # Ensure session is in clean state before starting
    _ensure_session_clean(db.session)

    try:
        # Only process the main log file, not rotated ones
        # Rotated logs contain data we already processed when they were the main log
        if not os.path.exists(log_file_path):
            logger.warning(f"Log file not found: {log_file_path}")
            return True

        # For HPC experiments, check if we have old incorrectly parsed data
        # If simulation time is missing/zero, reset and re-parse from beginning
        if is_hpc:
            existing_metric = ServerLogMetrics.query.filter_by(
                exp_id=exp_id, aggregation_level="daily"
            ).first()

            if (
                existing_metric
                and existing_metric.min_time
                and existing_metric.max_time
            ):
                # Check if this looks like old data (simulation time near zero)
                sim_time = (
                    existing_metric.max_time - existing_metric.min_time
                ).total_seconds()
                if sim_time < 1.0:  # Less than 1 second suggests old incorrect data
                    logger.info(
                        f"Found old server metrics with near-zero simulation time for exp_id={exp_id}, resetting"
                    )
                    reset_hpc_server_metrics(exp_id)

        # Get relative file name (for storage in database)
        file_name = os.path.basename(log_file_path)

        # Get last offset for this specific file
        last_offset = get_log_file_offset(exp_id, "server", file_name)

        # Check if file has been rotated (size is smaller than offset)
        file_size = os.path.getsize(log_file_path)
        if file_size < last_offset:
            # File was rotated, reset offset to read from beginning
            logger.info(
                f"Log file {file_name} was rotated (size {file_size} < offset {last_offset}), resetting offset"
            )
            last_offset = 0

        # Parse log file incrementally
        new_offset, metrics = parse_server_log_incremental(
            log_file_path, exp_id, last_offset, is_hpc=is_hpc
        )

        # Update offset
        if new_offset > last_offset:
            update_log_file_offset(exp_id, "server", file_name, new_offset)

        return True

    except Exception as e:
        logger.error(f"Error updating server log metrics: {e}", exc_info=True)
        return False


def update_client_log_metrics(exp_id, client_id, log_file_path, is_hpc=False):
    """
    Update client log metrics by reading new log entries.

    Only processes the main log file ({client_name}_client.log) for incremental updates.
    Rotated log files (.log.1, .log.2, etc.) are skipped because their content
    was already processed when they were the main log file.

    Args:
        exp_id: Experiment ID
        client_id: Client ID
        log_file_path: Full path to the client log file
        is_hpc: Boolean flag indicating if this is an HPC experiment (uses different log format)

    Returns:
        bool: True if successful, False otherwise
    """
    # Ensure session is in clean state before starting
    _ensure_session_clean(db.session)

    try:
        # Only process the main log file, not rotated ones
        # Rotated logs contain data we already processed when they were the main log
        if not os.path.exists(log_file_path):
            logger.warning(f"Client log file not found: {log_file_path}")
            return True

        # For HPC experiments, check if we have old incorrectly parsed data
        # If we find "unknown" method name, reset and re-parse from beginning
        if is_hpc:
            has_unknown = ClientLogMetrics.query.filter_by(
                exp_id=exp_id, client_id=client_id, method_name="unknown"
            ).first()

            if has_unknown:
                logger.info(
                    f"Found 'unknown' method in HPC client metrics, resetting for exp_id={exp_id}, client_id={client_id}"
                )
                reset_hpc_client_metrics(exp_id, client_id)

        # Get relative file path (for storage in database)
        file_name = os.path.basename(log_file_path)

        # Get last offset for this specific file
        last_offset = get_log_file_offset(exp_id, "client", file_name, client_id)

        # Check if file has been rotated (size is smaller than offset)
        file_size = os.path.getsize(log_file_path)
        if file_size < last_offset:
            # File was rotated, reset offset to read from beginning
            logger.info(
                f"Client log file {file_name} was rotated (size {file_size} < offset {last_offset}), resetting offset"
            )
            last_offset = 0

        # Parse log file incrementally
        new_offset, metrics = parse_client_log_incremental(
            log_file_path, exp_id, client_id, last_offset, is_hpc=is_hpc
        )

        # Update offset
        if new_offset > last_offset:
            update_log_file_offset(exp_id, "client", file_name, new_offset, client_id)

        return True

    except Exception as e:
        logger.error(f"Error updating client log metrics: {e}", exc_info=True)
        return False
