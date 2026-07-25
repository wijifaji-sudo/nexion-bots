import os
import json
import logging
import httpx

from config import USER_DATA_DIR

logger = logging.getLogger(__name__)

GIST_API = "https://api.github.com/gists"
_GIST_ID_FILE = os.path.join(USER_DATA_DIR, "_gist_id.json")


def load_gist_id():
    if os.path.exists(_GIST_ID_FILE):
        try:
            with open(_GIST_ID_FILE) as f:
                data = json.load(f)
                return data.get("gist_id", "")
        except Exception:
            pass
    return ""


def save_gist_id(gist_id):
    try:
        with open(_GIST_ID_FILE, "w") as f:
            json.dump({"gist_id": gist_id}, f)
    except Exception as e:
        logger.error(f"Failed to save gist_id: {e}")


async def _get_headers(token):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


async def get_or_create_gist(token, gist_id, backup_data, user_count):
    filename = "nexionsnipe_backup.json"
    content = json.dumps(backup_data, indent=1)

    if not gist_id:
        gist_id = load_gist_id()

    headers = await _get_headers(token)

    async with httpx.AsyncClient(timeout=30) as client:
        if gist_id:
            try:
                resp = await client.patch(
                    f"{GIST_API}/{gist_id}",
                    headers=headers,
                    json={"files": {filename: {"content": content}}},
                )
                if resp.status_code == 200:
                    logger.info(f"Gist updated: {user_count} users")
                    return gist_id
                elif resp.status_code == 404:
                    logger.warning("Gist not found, creating new one")
                    gist_id = None
                else:
                    logger.error(f"Gist update failed: {resp.status_code} {resp.text[:200]}")
                    return gist_id
            except Exception as e:
                logger.error(f"Gist update error: {e}")
                return gist_id

        if not gist_id:
            try:
                resp = await client.post(
                    GIST_API,
                    headers=headers,
                    json={
                        "description": "NexionSnipe Bot Auto Backup",
                        "public": False,
                        "files": {filename: {"content": content}},
                    },
                )
                if resp.status_code == 201:
                    new_id = resp.json()["id"]
                    save_gist_id(new_id)
                    logger.info(f"Gist created: {new_id} ({user_count} users)")
                    return new_id
                else:
                    logger.error(f"Gist create failed: {resp.status_code} {resp.text[:200]}")
                    return None
            except Exception as e:
                logger.error(f"Gist create error: {e}")
                return None


async def fetch_backup_from_gist(token, gist_id):
    if not token:
        return None

    if not gist_id:
        gist_id = load_gist_id()

    if not gist_id:
        return None

    headers = await _get_headers(token)

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(f"{GIST_API}/{gist_id}", headers=headers)
            if resp.status_code != 200:
                logger.error(f"Gist fetch failed: {resp.status_code}")
                return None

            files = resp.json().get("files", {})
            for fname, fdata in files.items():
                if fname.endswith(".json"):
                    content = fdata.get("content", "")
                    return json.loads(content)

            logger.warning("No .json file found in gist")
            return None
        except Exception as e:
            logger.error(f"Gist fetch error: {e}")
            return None
