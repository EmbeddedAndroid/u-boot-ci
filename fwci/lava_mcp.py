"""Minimal client for the LAVA MCP endpoint (streamable HTTP, JSON-RPC).
The token comes from LAVA_TOKEN and is only ever sent as a header; job
records can carry per-job tokens, so callers keep to the fields they need."""
import json
import os
import re
import subprocess
import urllib.request

# How the LAVA MCP server reports a failed REST call in a tool error.
HTTP_ERROR = re.compile(r"-> HTTP (\d{3}): (.*)\Z", re.S)


class Rejected(RuntimeError):
    """LAVA answered the call with a client error (4xx other than a timeout
    or rate limit): the request was refused and changed nothing, so a
    refused submit_job created no job. message is LAVA's own text."""

    def __init__(self, tool, status, message):
        super().__init__("%s: HTTP %d: %s" % (tool, status, message))
        self.status = status
        self.message = message


def _rejection(tool, text):
    m = HTTP_ERROR.search(text)
    if not m:
        return None
    status = int(m.group(1))
    if not 400 <= status < 500 or status in (408, 429):
        return None
    body = m.group(2).strip()
    try:
        body = json.loads(body).get("message") or body
    except (ValueError, AttributeError):
        pass
    return Rejected(tool, status, str(body)[:1000])


class Lava:
    def __init__(self, url=None, token=None):
        self.url = url or os.environ.get("LAVA_MCP_URL", "https://lava.infra.foundries.io/mcp")
        self._token = token or os.environ["LAVA_TOKEN"]
        self._sid = None

    def _rpc(self, body):
        h = {"Content-Type": "application/json",
             "Accept": "application/json, text/event-stream",
             "X-Lava-Token": self._token}
        if self._sid:
            h["Mcp-Session-Id"] = self._sid
        r = urllib.request.urlopen(urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers=h), timeout=600)
        text = r.read().decode()
        self._sid = r.headers.get("Mcp-Session-Id") or self._sid
        if "data:" in text[:200]:
            text = [l[5:].strip() for l in text.splitlines() if l.startswith("data:")][-1]
        return json.loads(text) if text.strip() else {}

    def call(self, tool, **args):
        if self._sid is None:
            self._rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "fwci", "version": "1"}}})
            self._rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
        r = self._rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}})
        if "error" in r:
            raise RuntimeError("%s: %s" % (tool, json.dumps(r["error"])[:300]))
        text = "".join(c.get("text", "") for c in r["result"].get("content", []))
        if r["result"].get("isError"):
            raise _rejection(tool, text) or RuntimeError("%s: %s" % (tool, text[:1000]))
        try:
            return json.loads(text)
        except ValueError:
            return text

    def upload(self, path, ttl=43200):
        """Upload a file to the LAVA artifact store; returns (url, token
        name) for a deploy header. The upload token is used for the PUT only."""
        res = self.call("create_artifact_upload", filename=os.path.basename(path),
                        size_bytes=os.path.getsize(path), ttl_seconds=ttl)
        subprocess.run(["curl", "-fsS", "-o", "/dev/null", "-T", path, "-H",
                        "Authorization: " + res["token"], res["get_url"]], check=True)
        return res["get_url"], res["remote_artifact_token"]["name"]

    def submit(self, definition):
        r = self.call("submit_job", definition=definition)
        ids = r.get("job_ids") or r.get("ids") or [r.get("job_id") or r.get("id")]
        return int(ids[0])

    def job(self, job_id):
        j = self.call("get_job", job_id=job_id)
        return {k: j.get(k) for k in ("id", "state", "health", "actual_device",
                                       "start_time", "end_time")}

    def results(self, job_id):
        return self.call("get_job_results", job_id=job_id, limit=2000).get("results", [])

    def queue(self):
        return self.call("get_queue").get("results", [])

    def devices(self, device_type):
        r = self.call("list_devices", device_type=device_type, limit=200).get("results", [])
        return [{k: d.get(k) for k in ("hostname", "state", "health")} for d in r]

    def running(self, metadata):
        """Running jobs whose metadata matches (id, device type only)."""
        r = self.call("list_jobs", state="Running", metadata=metadata, limit=100).get("results", [])
        return [{"id": j["id"], "requested_device_type": j.get("requested_device_type")} for j in r]

    def log(self, job_id):
        r = self.call("get_job_logs", job_id=job_id)
        return r if isinstance(r, str) else r.get("logs") or json.dumps(r)
