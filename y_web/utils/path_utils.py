"""Path utilities for source-based execution."""

import os


def get_base_path():
    """
    Get the base path of the application.

    Returns:
        str: The base path of the application
    """
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_data_schema_path():
    """
    Get the path to the data_schema directory.

    Returns:
        str: Path to data_schema directory
    """
    return os.path.join(get_base_path(), "data_schema")


def get_y_web_path():
    """
    Get the path to the y_web directory.

    Returns:
        str: Path to y_web directory
    """
    return os.path.join(get_base_path(), "y_web")


def get_resource_path(relative_path):
    """
    Get absolute path to resource.

    Args:
        relative_path: Relative path from the base directory

    Returns:
        str: Absolute path to the resource
    """
    return os.path.join(get_base_path(), relative_path)


def get_writable_path(relative_path=""):
    """
    Get absolute path to writable directory for source execution.

    Args:
        relative_path: Relative path from the writable base directory

    Returns:
        str: Absolute path to the writable location
    """
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    if relative_path:
        return os.path.join(base, relative_path)
    return base
