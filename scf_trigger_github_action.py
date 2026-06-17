# -*- coding: utf8 -*-
import json
import os
import urllib.error
import urllib.request


GITHUB_API_VERSION = "2022-11-28"


def _get_event_value(event, key, default=None):
    if not isinstance(event, dict):
        return default

    if key in event and event[key] not in (None, ""):
        return event[key]

    query = event.get("queryString") or event.get("queryStringParameters") or {}
    if isinstance(query, dict) and query.get(key) not in (None, ""):
        return query[key]

    body = event.get("body")
    if isinstance(body, str) and body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and payload.get(key) not in (None, ""):
            return payload[key]

    return default


def _required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError("Missing required environment variable: " + name)
    return value


def _github_dispatch(owner, repo, workflow, ref, token, inputs):
    url = "https://api.github.com/repos/{}/{}/actions/workflows/{}/dispatches".format(
        owner, repo, workflow
    )
    payload = {
        "ref": ref,
    }
    if inputs:
        payload["inputs"] = inputs

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "tencent-scf-github-action-trigger",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("GitHub API error {}: {}".format(exc.code, body))
    except urllib.error.URLError as exc:
        raise RuntimeError("GitHub API request failed: {}".format(exc))


def main_handler(event, context):
    print("Received event: " + json.dumps(event, ensure_ascii=False, indent=2))
    print("Received context: " + str(context))

    token = _required_env("GITHUB_ACTION_KEY")

    owner = os.environ.get("GITHUB_OWNER", "bastarder")
    repo = os.environ.get("GITHUB_REPO", "titan-bot")
    workflow = os.environ.get("GITHUB_WORKFLOW", "daily-snapshot.yml")
    ref = _get_event_value(event, "ref", os.environ.get("GITHUB_REF", "main"))

    snapshot_date = _get_event_value(event, "snapshot_date", os.environ.get("SNAPSHOT_DATE", ""))
    readme_days = str(_get_event_value(event, "readme_days", os.environ.get("README_DAYS", "30")))

    inputs = {
        "readme_days": readme_days,
    }
    if snapshot_date:
        inputs["snapshot_date"] = str(snapshot_date)

    status, body = _github_dispatch(owner, repo, workflow, ref, token, inputs)

    result = {
        "ok": True,
        "status": status,
        "owner": owner,
        "repo": repo,
        "workflow": workflow,
        "ref": ref,
        "inputs": inputs,
    }
    if body:
        result["body"] = body

    print("Dispatch result: " + json.dumps(result, ensure_ascii=False))
    return result
