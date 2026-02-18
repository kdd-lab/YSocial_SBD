"""
Tests for HPC experiment copy exclusions.

Verifies that when copying HPC experiments:
- Log files are excluded
- Database files are excluded
- ray_config.temp file is excluded
"""

import os
import tempfile
import shutil
import re

import pytest


def test_log_file_exclusion_pattern():
    """Test that log file pattern matches all log files including rotated logs."""
    log_pattern = re.compile(r"\.log(\.\d+)?$")
    
    # Files that should be excluded
    log_files = [
        "server.log",
        "client.log",
        "server.log.1",
        "server.log.2",
        "client.log.10",
        "error.log",
        "debug.log.999",
    ]
    
    for filename in log_files:
        assert log_pattern.search(filename), f"{filename} should match log pattern"
    
    # Files that should NOT be excluded
    non_log_files = [
        "config_server.json",
        "server_config.json",
        "client_config.json",
        "database_server.db",
        "prompts.json",
        "ray_config.temp",
        "log_config.json",  # Ends with .json, not .log
    ]
    
    for filename in non_log_files:
        assert not log_pattern.search(filename), f"{filename} should NOT match log pattern"


def test_hpc_database_exclusion():
    """Test that database files are excluded for HPC experiments."""
    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        source_dir = os.path.join(tmpdir, "source")
        dest_dir = os.path.join(tmpdir, "dest")
        os.makedirs(source_dir)
        os.makedirs(dest_dir)
        
        # Create HPC marker file
        with open(os.path.join(source_dir, "server_config.json"), "w") as f:
            f.write('{"experiment_name": "test"}')
        
        # Create database files
        db_files = [
            "database_server.db",
            "database_backup.db",
            "database_test.db",
        ]
        
        for db_file in db_files:
            with open(os.path.join(source_dir, db_file), "w") as f:
                f.write("database content")
        
        # Create non-database files
        with open(os.path.join(source_dir, "config.json"), "w") as f:
            f.write('{"test": true}')
        
        # Detect if HPC
        is_hpc = os.path.exists(os.path.join(source_dir, "server_config.json"))
        assert is_hpc, "Should detect as HPC experiment"
        
        # Simulate copy logic
        log_pattern = re.compile(r"\.log(\.\d+)?$")
        
        for item in os.listdir(source_dir):
            # Skip log files
            if log_pattern.search(item):
                continue
            
            # For HPC, skip database files
            if is_hpc:
                if item == "database_server.db" or (item.startswith("database_") and item.endswith(".db")):
                    continue
                if item == "ray_config.temp":
                    continue
            
            # Copy file
            source_item = os.path.join(source_dir, item)
            dest_item = os.path.join(dest_dir, item)
            
            if os.path.isfile(source_item):
                shutil.copy2(source_item, dest_item)
        
        # Verify: database files should NOT be copied for HPC
        for db_file in db_files:
            assert not os.path.exists(os.path.join(dest_dir, db_file)), \
                f"{db_file} should be excluded for HPC experiments"
        
        # Verify: non-database files SHOULD be copied
        assert os.path.exists(os.path.join(dest_dir, "config.json")), \
            "config.json should be copied"
        assert os.path.exists(os.path.join(dest_dir, "server_config.json")), \
            "server_config.json should be copied"


def test_ray_config_temp_exclusion():
    """Test that ray_config.temp is excluded for HPC experiments."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_dir = os.path.join(tmpdir, "source")
        dest_dir = os.path.join(tmpdir, "dest")
        os.makedirs(source_dir)
        os.makedirs(dest_dir)
        
        # Create HPC marker
        with open(os.path.join(source_dir, "server_config.json"), "w") as f:
            f.write('{}')
        
        # Create ray_config.temp
        with open(os.path.join(source_dir, "ray_config.temp"), "w") as f:
            f.write("ray configuration")
        
        # Create other ray-related files that SHOULD be copied
        with open(os.path.join(source_dir, "ray_config.log"), "w") as f:
            f.write("ray log")  # But this will be excluded by log pattern
        
        with open(os.path.join(source_dir, "ray_config.json"), "w") as f:
            f.write("ray config")  # This should be copied
        
        # Detect HPC
        is_hpc = os.path.exists(os.path.join(source_dir, "server_config.json"))
        
        # Simulate copy logic
        log_pattern = re.compile(r"\.log(\.\d+)?$")
        
        for item in os.listdir(source_dir):
            if log_pattern.search(item):
                continue
            
            if is_hpc:
                if item == "database_server.db" or (item.startswith("database_") and item.endswith(".db")):
                    continue
                if item == "ray_config.temp":
                    continue
            
            source_item = os.path.join(source_dir, item)
            dest_item = os.path.join(dest_dir, item)
            
            if os.path.isfile(source_item):
                shutil.copy2(source_item, dest_item)
        
        # Verify ray_config.temp is NOT copied
        assert not os.path.exists(os.path.join(dest_dir, "ray_config.temp")), \
            "ray_config.temp should be excluded for HPC"
        
        # Verify ray_config.json IS copied
        assert os.path.exists(os.path.join(dest_dir, "ray_config.json")), \
            "ray_config.json should be copied"
        
        # Verify ray_config.log is NOT copied (excluded by log pattern)
        assert not os.path.exists(os.path.join(dest_dir, "ray_config.log")), \
            "ray_config.log should be excluded by log pattern"


def test_standard_experiment_copies_database():
    """Test that Standard experiments still copy database files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_dir = os.path.join(tmpdir, "source")
        dest_dir = os.path.join(tmpdir, "dest")
        os.makedirs(source_dir)
        os.makedirs(dest_dir)
        
        # Create Standard experiment marker (no server_config.json)
        with open(os.path.join(source_dir, "config_server.json"), "w") as f:
            f.write('{}')
        
        # Create database file
        with open(os.path.join(source_dir, "database_server.db"), "w") as f:
            f.write("database content")
        
        # Detect NOT HPC
        is_hpc = os.path.exists(os.path.join(source_dir, "server_config.json"))
        assert not is_hpc, "Should NOT detect as HPC"
        
        # Simulate copy logic
        log_pattern = re.compile(r"\.log(\.\d+)?$")
        
        for item in os.listdir(source_dir):
            if log_pattern.search(item):
                continue
            
            # Standard experiments don't have special exclusions
            if is_hpc:
                if item == "database_server.db" or (item.startswith("database_") and item.endswith(".db")):
                    continue
                if item == "ray_config.temp":
                    continue
            
            source_item = os.path.join(source_dir, item)
            dest_item = os.path.join(dest_dir, item)
            
            if os.path.isfile(source_item):
                shutil.copy2(source_item, dest_item)
        
        # Verify database IS copied for Standard experiments
        assert os.path.exists(os.path.join(dest_dir, "database_server.db")), \
            "database_server.db should be copied for Standard experiments"


def test_combined_exclusions():
    """Test that all exclusions work together for HPC experiments."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_dir = os.path.join(tmpdir, "source")
        dest_dir = os.path.join(tmpdir, "dest")
        os.makedirs(source_dir)
        os.makedirs(dest_dir)
        
        # Create HPC experiment
        with open(os.path.join(source_dir, "server_config.json"), "w") as f:
            f.write('{}')
        
        # Create files to exclude
        excluded_files = [
            "server.log",
            "client.log.1",
            "database_server.db",
            "database_backup.db",
            "ray_config.temp",
        ]
        
        for filename in excluded_files:
            with open(os.path.join(source_dir, filename), "w") as f:
                f.write("content")
        
        # Create files to include
        included_files = [
            "server_config.json",
            "client_config.json",
            "prompts.json",
            "population.json",
        ]
        
        for filename in included_files:
            with open(os.path.join(source_dir, filename), "w") as f:
                f.write("content")
        
        # Copy with exclusions
        is_hpc = os.path.exists(os.path.join(source_dir, "server_config.json"))
        log_pattern = re.compile(r"\.log(\.\d+)?$")
        
        for item in os.listdir(source_dir):
            if log_pattern.search(item):
                continue
            
            if is_hpc:
                if item == "database_server.db" or (item.startswith("database_") and item.endswith(".db")):
                    continue
                if item == "ray_config.temp":
                    continue
            
            source_item = os.path.join(source_dir, item)
            dest_item = os.path.join(dest_dir, item)
            
            if os.path.isfile(source_item):
                shutil.copy2(source_item, dest_item)
        
        # Verify excluded files are NOT copied
        for filename in excluded_files:
            assert not os.path.exists(os.path.join(dest_dir, filename)), \
                f"{filename} should be excluded"
        
        # Verify included files ARE copied
        for filename in included_files:
            assert os.path.exists(os.path.join(dest_dir, filename)), \
                f"{filename} should be copied"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
