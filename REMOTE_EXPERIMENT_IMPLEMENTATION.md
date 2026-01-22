# Remote Experiment Support - Implementation Summary

## Overview
This implementation adds support for remote experiments in YSocial, allowing users to configure experiments to run on remote servers instead of only locally.

## Changes Made

### 1. Database Schema (Migration)
**File:** `y_web/migrations/add_remote_experiment_fields.py`

Added three new columns to the `exps` table:
- `is_remote` (INTEGER, default: 0) - Flag indicating if experiment is remote (0=local, 1=remote)
- `remote_host` (VARCHAR/TEXT, nullable) - Host address for remote server (e.g., IP address or domain)
- `remote_port` (INTEGER, nullable) - Port for remote server connection

The migration supports both SQLite and PostgreSQL databases and safely checks for existing columns before adding them.

### 2. Data Model
**File:** `y_web/models.py`

Updated the `Exps` model to include the new fields:
```python
is_remote = db.Column(db.Integer, nullable=False, default=0)
remote_host = db.Column(db.String(255), nullable=True, default=None)
remote_port = db.Column(db.Integer, nullable=True, default=None)
```

### 3. User Interface
**File:** `y_web/templates/admin/settings.html`

Added UI elements to the "New Experiment" form:

#### Toggle Switch
- "Experiment Type" toggle to select between local (default) and remote
- Label clearly indicates "Remote Experiment"

#### Remote Configuration Box
- Conditionally displayed when remote is selected
- **Host Address** input field with placeholder "e.g., 192.168.1.100 or example.com"
- **Port** input field (default: 8000, range: 1-65535)
- Clean, consistent styling matching the existing form design

#### JavaScript Behavior
- Toggle automatically shows/hides remote configuration fields
- Makes host/port fields required when remote is selected
- Removes required attribute when switching back to local

### 4. Backend Logic
**File:** `y_web/routes_admin/experiments_routes.py`

#### Form Processing in `create_experiment()` route:
- Parses `is_remote` flag from form data
- Validates remote configuration when `is_remote=1`:
  - Checks remote_host is not empty
  - Validates hostname/IP format using regex pattern
  - Validates remote_port is provided and is a valid integer
  - Ensures port is in valid range (1-65535)
  - Returns user-friendly error messages for validation failures

#### Database Storage:
- Stores all three remote fields in the `Exps` database record
- Maintains backward compatibility (existing experiments default to local)

#### Config Generation:
Updated function signatures:
```python
def generate_standard_config(..., is_remote=False, remote_host=None, remote_port=None)
def generate_hpc_config(..., is_remote=False, remote_host=None, remote_port=None)
```

Both functions now:
- Include `is_remote` flag in generated config
- Add `remote_host` and `remote_port` fields when `is_remote=True`
- Maintain backward compatibility with existing configurations

### 5. Configuration Files

#### Standard Experiments (config_server.json)
New fields added when remote:
```json
{
  "is_remote": true,
  "remote_host": "192.168.1.100",
  "remote_port": 8080,
  ...
}
```

#### HPC Experiments (server_config.json)
Same fields added to HPC configuration with identical structure.

### 6. Tests
**File:** `y_web/tests/test_remote_experiment_support.py`

Comprehensive test suite covering:
- Model field existence validation
- Config generation for local experiments
- Config generation for remote experiments (both Standard and HPC)
- Remote host/port validation logic
- Model default values verification

## Usage

### Creating a Local Experiment (Default)
1. Go to Admin > Experiments
2. Fill in experiment details
3. Leave "Remote Experiment" toggle OFF
4. Create experiment normally

### Creating a Remote Experiment
1. Go to Admin > Experiments
2. Fill in experiment details
3. Enable "Remote Experiment" toggle
4. Enter remote server details:
   - Host Address: IP address or domain name (e.g., 192.168.1.100)
   - Port: Server port (default 8000, range 1-65535)
5. Create experiment

The remote configuration will be stored in the database and included in the experiment's config file.

## Backward Compatibility

All changes maintain full backward compatibility:
- Existing experiments default to `is_remote=0` (local)
- Database migration adds columns with proper defaults
- Config generation functions use optional parameters with defaults
- UI defaults to local experiment mode

## Security Considerations

- Input validation for hostname/IP format prevents injection attacks
- Port range validation ensures valid port numbers
- User-friendly error messages without exposing system details
- CodeQL security scan passed with 0 vulnerabilities

## Database Migration

To apply the migration to an existing installation:

```bash
cd /path/to/YSocial
python y_web/migrations/add_remote_experiment_fields.py
```

The script will:
- Automatically detect SQLite databases in standard locations
- Support PostgreSQL if environment variables are configured
- Skip columns that already exist
- Provide clear success/failure messages

## Files Modified

1. `y_web/models.py` - Added remote fields to Exps model
2. `y_web/templates/admin/settings.html` - Added UI for remote configuration
3. `y_web/routes_admin/experiments_routes.py` - Added backend logic and validation
4. `y_web/migrations/add_remote_experiment_fields.py` - Database migration script (new)
5. `y_web/tests/test_remote_experiment_support.py` - Test suite (new)
6. `data_schema/database_dashboard.db` - Updated with new schema

## Future Enhancements

Potential improvements for future releases:
- Connection testing before saving remote configuration
- SSH tunnel support for secure remote connections
- Remote server status monitoring
- Batch remote server configuration
- Remote server templates/presets
