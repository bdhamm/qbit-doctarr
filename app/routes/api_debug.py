"""Read-only diagnostic endpoints. Curl-only, not exposed in the web UI."""

import json
from urllib.request import Request, build_opener
from urllib.error import HTTPError

from flask import jsonify

from ..core.tasks._shared.config import resolve_api_version, _arr_family
from ._shared import load_config
from . import bp


def _debug_resource_for_family(family):
    """Map *arr family to its primary resource for the generic debug endpoint."""
    return {
        "radarr": "movie",
        "sonarr": "series",
        "lidarr": "artist",
        "readarr": "author",
        "chaptarr": "author",
    }.get(family)


@bp.route('/api/debug/arrs')
def debug_arrs():
    config = load_config()
    result = []
    for arr in config.get("arrs", []):
        result.append({
            "name": arr.get("name", "Unknown"),
            "type": arr.get("type", "radarr"),
            "enabled": bool(arr.get("enabled", True)),
            "family": _arr_family(arr),
            "api_version": resolve_api_version(
                arr.get("type", "radarr"),
                arr.get("api_version", "auto"),
            ),
        })
    return jsonify({"arrs": result})


@bp.route('/api/debug/<string:arr_type>/<int:item_id>')
def debug_item(arr_type, item_id):
    config = load_config()
    arr_type = (arr_type or "").strip().lower()
    candidates = [
        a for a in config.get("arrs", [])
        if (a.get("type") or "").lower() == arr_type
    ]
    if not candidates:
        configured = sorted({(a.get("type") or "").lower() for a in config.get("arrs", [])})
        return jsonify({
            "source": "doctarr",
            "error": f"No *arr configured with type '{arr_type}'.",
            "configured_types": configured,
            "hint": "Call /api/debug/arrs to see the full list.",
        }), 404

    if len(candidates) > 1:
        return jsonify({
            "source": "doctarr",
            "error": f"Multiple *arrs of type '{arr_type}' are configured; lookup by type is ambiguous.",
            "candidate_names": [a.get("name", "Unknown") for a in candidates],
        }), 400

    arr = candidates[0]
    arr_name = arr.get("name", "Unknown")
    if not arr.get("enabled", True):
        return jsonify({
            "source": "doctarr",
            "error": f"*arr '{arr_name}' is disabled in config.",
            "arr": arr_name,
            "type": arr_type,
        }), 400

    family = _arr_family(arr)
    resource = _debug_resource_for_family(family)
    if not resource:
        return jsonify({
            "source": "doctarr",
            "error": f"Unsupported *arr family '{family}' for type '{arr_type}'.",
            "arr": arr_name,
        }), 400

    api_url = arr["url"].rstrip("/")
    api_key = arr["api_key"]
    api_ver = resolve_api_version(arr.get("type", "radarr"), arr.get("api_version", "auto"))
    upstream_path = f"/api/{api_ver}/{resource}/{item_id}"

    try:
        req = Request(f"{api_url}{upstream_path}", headers={"X-Api-Key": api_key})
        with build_opener().open(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return jsonify({
            "source": "arr",
            "status": 200,
            "arr": arr_name,
            "type": arr_type,
            "family": family,
            "api_version": api_ver,
            "resource": resource,
            "item_id": item_id,
            "upstream_path": upstream_path,
            "data": data,
        })
    except HTTPError as e:
        raw_body = ""
        try:
            raw_body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        try:
            body = json.loads(raw_body) if raw_body else None
        except Exception:
            body = raw_body
        return jsonify({
            "source": "arr",
            "status": e.code,
            "arr": arr_name,
            "type": arr_type,
            "family": family,
            "api_version": api_ver,
            "resource": resource,
            "item_id": item_id,
            "upstream_path": upstream_path,
            "error": f"*arr returned HTTP {e.code}",
            "body": body,
        }), e.code
    except Exception as e:
        return jsonify({
            "source": "network",
            "status": 0,
            "arr": arr_name,
            "type": arr_type,
            "family": family,
            "api_version": api_ver,
            "resource": resource,
            "item_id": item_id,
            "upstream_path": upstream_path,
            "error": f"{type(e).__name__}: {e}",
        }), 502


@bp.route('/api/debug/sonarr/episode/<int:episode_id>')
def debug_sonarr_episode(episode_id):
    config = load_config()

    candidates = [
        a for a in config.get("arrs", [])
        if (a.get("type") or "").lower() == "sonarr"
    ]
    if not candidates:
        return jsonify({
            "source": "doctarr",
            "error": "No *arr configured with type 'sonarr'.",
            "hint": "Call /api/debug/arrs to see the full list.",
        }), 404

    if len(candidates) > 1:
        return jsonify({
            "source": "doctarr",
            "error": "Multiple *arrs of type 'sonarr' are configured; lookup by type is ambiguous.",
            "candidate_names": [a.get("name", "Unknown") for a in candidates],
        }), 400

    arr = candidates[0]
    arr_name = arr.get("name", "Unknown")
    if not arr.get("enabled", True):
        return jsonify({
            "source": "doctarr",
            "error": f"*arr '{arr_name}' is disabled in config.",
            "arr": arr_name,
        }), 400

    api_url = arr["url"].rstrip("/")
    api_key = arr["api_key"]
    api_ver = resolve_api_version("sonarr", arr.get("api_version", "auto"))

    ep_path = f"/api/{api_ver}/episode/{episode_id}"
    try:
        ep_req = Request(f"{api_url}{ep_path}", headers={"X-Api-Key": api_key})
        with build_opener().open(ep_req, timeout=10) as resp:
            episode = json.loads(resp.read())
    except HTTPError as e:
        raw_body = ""
        try:
            raw_body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        try:
            body = json.loads(raw_body) if raw_body else None
        except Exception:
            body = raw_body
        return jsonify({
            "source": "arr",
            "status": e.code,
            "arr": arr_name,
            "error": f"*arr returned HTTP {e.code} looking up episode {episode_id}",
            "body": body,
            "upstream_path": ep_path,
        }), e.code
    except Exception as e:
        return jsonify({
            "source": "network",
            "status": 0,
            "arr": arr_name,
            "error": f"{type(e).__name__}: {e}",
            "upstream_path": ep_path,
        }), 502

    series_id = episode.get("seriesId")
    if not series_id:
        return jsonify({
            "source": "arr",
            "status": 200,
            "arr": arr_name,
            "error": f"Episode {episode_id} returned no seriesId field.",
            "episode": episode,
        }), 500

    se_path = f"/api/{api_ver}/series/{series_id}"
    try:
        se_req = Request(f"{api_url}{se_path}", headers={"X-Api-Key": api_key})
        with build_opener().open(se_req, timeout=10) as resp:
            series = json.loads(resp.read())
    except Exception as e:
        return jsonify({
            "source": "network",
            "status": 0,
            "arr": arr_name,
            "episode_id": episode_id,
            "series_id": series_id,
            "error": f"Episode lookup succeeded but series fetch failed: {type(e).__name__}: {e}",
        }), 502

    return jsonify({
        "source": "arr",
        "status": 200,
        "arr": arr_name,
        "type": "sonarr",
        "api_version": api_ver,
        "episode_id": episode_id,
        "series_id": series_id,
        "series_title": series.get("title"),
        "series_monitored": series.get("monitored"),
        "series_ended": series.get("ended"),
        "series_status": series.get("status"),
        "episode": {
            "seasonNumber": episode.get("seasonNumber"),
            "episodeNumber": episode.get("episodeNumber"),
            "title": episode.get("title"),
            "monitored": episode.get("monitored"),
            "hasFile": episode.get("hasFile"),
        },
        "seasons": [
            {"seasonNumber": s.get("seasonNumber"), "monitored": s.get("monitored")}
            for s in (series.get("seasons") or [])
        ],
        "hint": f"For full series state, GET /api/debug/sonarr/{series_id}",
    })