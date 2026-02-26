import requests


def check_for_updates():
    """
    Check for the latest release of YSocial and compare it with the current version.

    Returns:
        dict: Information about the latest release and download links.
    """

    current_version = "0.0.0"
    if current_version is None:
        return None

    else:
        current_version = current_version.strip("v")

    latest_release = __get_latest_release()
    if latest_release is None:
        return None

    latest_tag = latest_release["tag"].strip("v")

    if version_tuple(latest_tag) > version_tuple(current_version):
        # Source build: always use GitHub release page.
        url = f"https://github.com/YSocialTwin/YSocial/releases/tag/{latest_release['tag']}"
        published = latest_release.get("published_at")
        size = None
        sha = None

        return {
            "latest_version": latest_tag,
            "release_name": latest_release["name"],
            "published_at": latest_release.get("published_at"),
            "download_url": url,
            "size": size,
            "sha256": sha,
        }
    else:
        return None


def version_tuple(v):
    return tuple(map(int, v.split(".")))


def __get_latest_release():
    """
    Fetch the latest release information from the YSocial GitHub repository.

    Returns:
        dict: Release information (tag, name, assets, etc.) or None if not found.
    """
    url = f"https://api.github.com/repos/YSocialTwin/YSocial/releases/latest"
    response = requests.get(url, headers={"Accept": "application/vnd.github+json"})

    if response.status_code == 200:
        data = response.json()
        return {
            "tag": data.get("tag_name"),
            "name": data.get("name"),
            "published_at": data.get("published_at"),
        }
    else:
        print(f"Error: {response.status_code} — {response.text}")
        return None


def download_file(url, dest_path, exp_size, exp_sha256):
    """
    Download a file from a URL to a specified destination path.

    Args:
        url (str): URL of the file to download.
        dest_path (str): Local path to save the downloaded file.
    """
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    # check file size and sha256
    import hashlib
    import os

    actual_size = os.path.getsize(dest_path)
    if actual_size != exp_size:
        return False, "File size mismatch"
    sha256_hash = hashlib.sha256()
    with open(dest_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    actual_sha256 = sha256_hash.hexdigest()
    if actual_sha256 != exp_sha256:
        return False, "SHA256 mismatch"
    print(f"Update downloaded successfully")
    return True, "File downloaded and verified successfully."


def update_release_info_in_db():
    """
    Check for updates and store/update release information in the database.

    This function should be called at application startup to check for new releases.
    It updates a single-row table with the latest release information.

    Returns:
        tuple: (has_update: bool, release_info: dict or None)
    """
    from datetime import datetime

    try:
        print("Updating release information...")
        release_info = check_for_updates()
        print("Release info from update check:", release_info)
        # Import here to avoid circular imports
        from y_web import db
        from y_web.models import ReleaseInfo

        # Get or create the single row
        record = ReleaseInfo.query.first()

        if record is None:
            record = ReleaseInfo()
            db.session.add(record)

        # Update the record with current check time
        record.latest_check_on = datetime.utcnow().isoformat()

        if release_info:
            # New version available
            record.latest_version_tag = release_info.get("latest_version")
            record.release_name = release_info.get("release_name")
            record.published_at = release_info.get("published_at")
            record.download_url = release_info.get("download_url")
            record.size = release_info.get("size")
            record.sha256 = release_info.get("sha256")

            db.session.commit()
            return True, release_info
        else:

            # No new version or unable to check
            db.session.commit()
            return False, None

    except Exception as e:
        print(f"Error checking for updates: {e}")
        return False, None
