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
                        # HPC server log format: individual request entries
                        # Format: {"request_id": "...", "client_name": "dsf", "path": "get_unreplied_mentions",
                        #          "status_code": 200, "duration": 0.0008, "time": "2026-01-19T12:54:00.784189+00:00",
                        #          "tid": "...", "day": 1, "hour": 3}

                        # Extract required fields
                        day = log_entry.get("day")
                        hour = log_entry.get("hour")
                        duration = float(log_entry.get("duration", 0))
                        path = log_entry.get("path", "unknown")

                        # Skip entries without day field
                        if day is None:
                            if line_count <= 5:
                                errors.append(f"Line {line_count}: Missing day field")
                            continue

                        # Parse timestamp if available for time tracking
                        time_str = log_entry.get("time", "")
                        time_obj = None
                        if time_str:
                            try:
                                # Handle ISO format with timezone
                                if "T" in time_str:
                                    # Remove timezone info for parsing
                                    time_str_clean = time_str.split("+")[0].split("Z")[
                                        0
                                    ]
                                    time_obj = datetime.fromisoformat(time_str_clean)
                                else:
                                    time_obj = datetime.strptime(
                                        time_str, "%Y-%m-%d %H:%M:%S"
                                    )
                            except (ValueError, AttributeError):
                                pass

                        # Aggregate by day
                        if day is not None:
                            hpc_daily_count += 1
                            daily_data[day][path]["count"] += 1
                            daily_data[day][path]["duration"] += duration
                            # For simulation_time, we'll calculate from timestamp differences later
                            if time_obj:
                                daily_data[day][path]["times"].append(time_obj)

                        # Aggregate by day-hour
                        if day is not None and hour is not None:
                            hpc_hourly_count += 1
                            key = f"{day}-{hour}"
                            hourly_data[key][path]["count"] += 1
                            hourly_data[key][path]["duration"] += duration
                            # For simulation_time, we'll calculate from timestamp differences later
                            if time_obj:
                                hourly_data[key][path]["times"].append(time_obj)
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
                        errors.append(
                            f"Line {line_count}: JSON decode error: {str(e)[:100]}"
                        )
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
            # Calculate simulation time from timestamp differences
            if data["times"]:
                min_time = min(data["times"])
                max_time = max(data["times"])
                # Simulation time is the time span covered by this aggregation period
                simulation_time = (max_time - min_time).total_seconds()
            else:
                min_time = None
                max_time = None
                simulation_time = 0

            # For HPC, store actual simulation time; for synthetic timestamps, use it
            if is_hpc:
                # For HPC: min_time and max_time are from actual timestamps
                # simulation_time is the difference (real elapsed time in simulation)
                pass
            else:
                # For standard experiments: simulation_time not used, keep existing logic
                simulation_time = 0

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
            # Calculate simulation time from timestamp differences
            if data["times"]:
                min_time = min(data["times"])
                max_time = max(data["times"])
                # Simulation time is the time span covered by this aggregation period
                simulation_time = (max_time - min_time).total_seconds()
            else:
                min_time = None
                max_time = None
                simulation_time = 0

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

    # Verify database writes for HPC experiments
    if is_hpc:
        daily_count = ServerLogMetrics.query.filter_by(
            exp_id=exp_id, aggregation_level="daily"
        ).count()
        hourly_count = ServerLogMetrics.query.filter_by(
            exp_id=exp_id, aggregation_level="hourly"
        ).count()
        print(f"\n=== HPC Database Write Verification (exp_id={exp_id}) ===")
        print(f"Daily records in database: {daily_count}")
        print(f"Hourly records in database: {hourly_count}")
        print("======================================================\n")

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


def check_hpc_client_execution_completion(exp_id, client_id, execution_log_path):
    """
    Check if an HPC client has completed execution by reading the execution log.
    
    Looks for the "Client shutdown complete" message in the last line of the
    execution log file. If found, updates the client_execution table to mark
    the client as completed.
    
    Args:
        exp_id: Experiment ID
        client_id: Client ID
        execution_log_path: Full path to the {client_name}_execution.log file
    
    Returns:
        bool: True if client is completed (shutdown message found), False otherwise
    """
    if not os.path.exists(execution_log_path):
        print(f"[HPC Monitor] Execution log does not exist: {execution_log_path}")
        return False
    
    try:
        # Read the last line of the log file
        with open(execution_log_path, 'r') as f:
            # Efficiently read last line by seeking to end
            # Handle both small and large files
            try:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                
                if file_size == 0:
                    print(f"[HPC Monitor] Execution log is empty: {execution_log_path}")
                    return False
                
                # Read up to 10KB from the end to find the last line
                # This handles cases where the last line might be very long
                chunk_size = min(10240, file_size)
                f.seek(max(0, file_size - chunk_size))
                lines = f.read().splitlines()
                
                if not lines:
                    print(f"[HPC Monitor] No lines found in execution log: {execution_log_path}")
                    return False
                
                last_line = lines[-1].strip()
                print(f"[HPC Monitor] Last line from {execution_log_path}: {last_line[:200]}...")
            except Exception as e:
                print(f"[HPC Monitor] Error seeking in file, using fallback: {e}")
                # Fallback: read entire file if seeking fails
                f.seek(0)
                lines = f.readlines()
                if not lines:
                    return False
                last_line = lines[-1].strip()
        
        # Parse the last line as JSON
        if not last_line:
            print(f"[HPC Monitor] Last line is empty")
            return False
        
        try:
            log_entry = json.loads(last_line)
            print(f"[HPC Monitor] Parsed JSON: {log_entry}")
        except json.JSONDecodeError as e:
            print(f"[HPC Monitor] Failed to parse JSON: {e}")
            return False
        
        # Check if the message indicates client shutdown complete
        message = log_entry.get("message", "")
        print(f"[HPC Monitor] Message field: '{message}'")
        
        if message == "Client shutdown complete":
            print(f"[HPC Monitor] *** MATCH: Client shutdown complete message found! ***")
            logger.info(
                f"HPC client {client_id} shutdown detected for experiment {exp_id}"
            )
            return True
        
        print(f"[HPC Monitor] Message does not match 'Client shutdown complete'")
        return False
        
    except Exception as e:
        logger.error(
            f"Error checking execution log for client {client_id}: {e}",
            exc_info=True
        )
        print(f"[HPC Monitor] Exception checking execution log: {e}")
        return False


def mark_hpc_client_as_completed(exp_id, client_id):
    """
    Mark an HPC client as completed in the client_execution table.
    
    Updates the client_execution record with:
    - elapsed_time = expected_duration_rounds
    - last_active_day and last_active_hour calculated from expected_duration_rounds
    - client status set to stopped (0)
    
    Args:
        exp_id: Experiment ID
        client_id: Client ID
    
    Returns:
        bool: True if successfully marked as completed, False otherwise
    """
    try:
        print(f"[HPC Monitor] Marking client {client_id} as completed...")
        
        # Get client execution record
        client_exec = Client_Execution.query.filter_by(client_id=client_id).first()
        if not client_exec:
            logger.warning(
                f"No client_execution record found for client {client_id}"
            )
            print(f"[HPC Monitor] No client_execution record found for client {client_id}")
            return False
        
        # Get the client to verify it exists
        client = Client.query.filter_by(id=client_id).first()
        if not client:
            logger.warning(f"Client {client_id} not found")
            print(f"[HPC Monitor] Client {client_id} not found")
            return False
        
        print(f"[HPC Monitor] Client name: {client.name}, current status: {client.status}")
        print(f"[HPC Monitor] Expected duration: {client_exec.expected_duration_rounds} rounds")
        
        # Calculate max day and hour from expected_duration_rounds
        # Since each experiment has its own database and the Rounds table is in db_exp,
        # it's more reliable to calculate from expected_duration_rounds
        # Assuming day 0, hour 0 = round 1 (as per HPC format in parse_client_log_incremental)
        if client_exec.expected_duration_rounds > 0:
            total_hours = client_exec.expected_duration_rounds - 1
            max_day = total_hours // 24
            max_hour = total_hours % 24
        else:
            # Default to 0,0 if no rounds configured
            max_day = 0
            max_hour = 0
        
        # Update client_execution record
        client_exec.elapsed_time = client_exec.expected_duration_rounds
        client_exec.last_active_day = max_day
        client_exec.last_active_hour = max_hour
        
        print(f"[HPC Monitor] Setting: elapsed_time={client_exec.elapsed_time}, last_active_day={max_day}, last_active_hour={max_hour}")
        
        # Mark client as stopped (client is guaranteed to exist from earlier check)
        client.status = 0
        print(f"[HPC Monitor] Setting client status to 0 (stopped)")
        
        logger.info(
            f"Marked HPC client {client_id} as completed: "
            f"elapsed_time={client_exec.elapsed_time}, "
            f"last_active_day={max_day}, last_active_hour={max_hour}"
        )
        
        # Commit changes
        print(f"[HPC Monitor] Committing changes to database...")
        _commit_with_retry(db.session)
        print(f"[HPC Monitor] *** Client {client.name} successfully marked as completed ***")
        return True
        
    except Exception as e:
        logger.error(
            f"Error marking client {client_id} as completed: {e}",
            exc_info=True
        )
        db.session.rollback()
        return False


def check_and_terminate_hpc_experiment(exp_id):
    """
    Check if all clients of an HPC experiment are completed and terminate the server if so.
    
    Args:
        exp_id: Experiment ID
    
    Returns:
        bool: True if experiment was terminated, False otherwise
    """
    try:
        from y_web.models import Exps
        from y_web.utils.external_processes import stop_hpc_server
        
        # Get the experiment
        exp = Exps.query.filter_by(idexp=exp_id).first()
        if not exp:
            print(f"[HPC Monitor] Experiment {exp_id} not found")
            return False
        
        # Only process HPC experiments that are running
        if exp.simulator_type != "HPC" or exp.running != 1:
            print(f"[HPC Monitor] Experiment {exp.exp_name} is not HPC or not running (type={exp.simulator_type}, running={exp.running})")
            return False
        
        # Get all clients for this experiment
        clients = Client.query.filter_by(id_exp=exp_id).all()
        if not clients:
            print(f"[HPC Monitor] No clients found for experiment {exp.exp_name}")
            return False
        
        # Check if all clients are completed (status = 0)
        completed_count = sum(1 for client in clients if client.status == 0)
        total_count = len(clients)
        print(f"[HPC Monitor] Experiment {exp.exp_name}: {completed_count}/{total_count} clients completed")
        
        all_completed = all(client.status == 0 for client in clients)
        
        if all_completed:
            print(f"[HPC Monitor] *** ALL CLIENTS COMPLETED for {exp.exp_name} ***")
            logger.info(
                f"All clients completed for HPC experiment {exp_id} ({exp.exp_name}). "
                f"Terminating server..."
            )
            
            # Terminate the server process
            print(f"[HPC Monitor] Calling stop_hpc_server for experiment {exp_id}...")
            stop_hpc_server(exp_id)
            print(f"[HPC Monitor] stop_hpc_server completed")
            
            # Update experiment status
            print(f"[HPC Monitor] Updating experiment status: setting running=0, exp_status='completed'")
            exp.running = 0
            exp.exp_status = "completed"
            _commit_with_retry(db.session)
            print(f"[HPC Monitor] *** EXPERIMENT {exp.exp_name} STATUS UPDATED: running={exp.running}, status={exp.exp_status} ***")
            
            logger.info(f"HPC experiment {exp_id} terminated successfully")
            return True
        
        return False
        
    except Exception as e:
        logger.error(
            f"Error checking/terminating HPC experiment {exp_id}: {e}",
            exc_info=True
        )
        print(f"[HPC Monitor] Error checking/terminating experiment {exp_id}: {e}")
        db.session.rollback()
        return False


def monitor_hpc_client_execution_logs():
    """
    Monitor execution logs for all active HPC experiments.
    
    For each running HPC client:
    1. Check if {client_name}_execution.log exists
    2. Check if last line contains "Client shutdown complete"
    3. If yes, mark client as completed and update client_execution table
    4. Check if all clients are completed and terminate server if so
    
    This function should be called periodically (e.g., every 5 seconds).
    """
    from y_web.models import Exps
    from y_web.utils.path_utils import get_writable_path
    
    BASE_DIR = get_writable_path()
    
    try:
        # Get all running HPC experiments
        hpc_experiments = Exps.query.filter_by(
            simulator_type="HPC", running=1
        ).all()
        
        if not hpc_experiments:
            print("[HPC Monitor] No active HPC experiments found")
            return
        
        print(f"[HPC Monitor] Monitoring {len(hpc_experiments)} active HPC experiment(s)")
        logger.debug(f"Monitoring {len(hpc_experiments)} active HPC experiment(s)")
        
        for exp in hpc_experiments:
            try:
                print(f"[HPC Monitor] Checking experiment: {exp.exp_name} (ID: {exp.idexp})")
                
                # Determine experiment folder path
                db_name = exp.db_name
                if db_name.startswith("experiments/") or db_name.startswith("experiments\\"):
                    parts = db_name.split(os.sep)
                    if len(parts) >= 2:
                        exp_folder = os.path.join(
                            BASE_DIR, f"y_web{os.sep}experiments{os.sep}{parts[1]}"
                        )
                    else:
                        print(f"[HPC Monitor] Invalid db_name format: {db_name}")
                        continue
                elif db_name.startswith("experiments_"):
                    uid = db_name.replace("experiments_", "")
                    exp_folder = os.path.join(
                        BASE_DIR, f"y_web{os.sep}experiments{os.sep}{uid}"
                    )
                else:
                    print(f"[HPC Monitor] Unknown db_name format: {db_name}")
                    continue
                
                print(f"[HPC Monitor] Experiment folder: {exp_folder}")
                
                # Get all running clients for this experiment
                clients = Client.query.filter_by(id_exp=exp.idexp, status=1).all()
                print(f"[HPC Monitor] Found {len(clients)} running client(s)")
                
                for client in clients:
                    print(f"[HPC Monitor] Checking client: {client.name} (ID: {client.id})")
                    
                    # Check if execution log exists (in logs/ subdirectory)
                    execution_log_path = os.path.join(
                        exp_folder, "logs", f"{client.name}_execution.log"
                    )
                    
                    print(f"[HPC Monitor] Looking for execution log: {execution_log_path}")
                    
                    if not os.path.exists(execution_log_path):
                        print(f"[HPC Monitor] Execution log not found for {client.name}")
                        continue
                    
                    print(f"[HPC Monitor] Execution log found, checking for shutdown message...")
                    
                    # Check if client has completed
                    if check_hpc_client_execution_completion(
                        exp.idexp, client.id, execution_log_path
                    ):
                        print(f"[HPC Monitor] *** SHUTDOWN DETECTED for {client.name} ***")
                        # Mark client as completed
                        if mark_hpc_client_as_completed(exp.idexp, client.id):
                            print(f"[HPC Monitor] Successfully marked {client.name} as completed")
                            logger.info(
                                f"Successfully marked client {client.name} as completed "
                                f"for experiment {exp.exp_name}"
                            )
                        else:
                            print(f"[HPC Monitor] Failed to mark {client.name} as completed")
                    else:
                        print(f"[HPC Monitor] No shutdown message found for {client.name}")
                
                # After processing all clients, check if experiment should be terminated
                print(f"[HPC Monitor] Checking if all clients completed for experiment {exp.exp_name}")
                if check_and_terminate_hpc_experiment(exp.idexp):
                    print(f"[HPC Monitor] *** EXPERIMENT {exp.exp_name} TERMINATED ***")
                
            except Exception as e:
                logger.error(
                    f"Error monitoring HPC experiment {exp.exp_name}: {e}",
                    exc_info=True
                )
                print(f"[HPC Monitor] Error monitoring experiment {exp.exp_name}: {e}")
                continue
    
    except Exception as e:
        logger.error(f"Error in HPC execution log monitoring: {e}", exc_info=True)
        print(f"[HPC Monitor] Error in monitoring: {e}")
