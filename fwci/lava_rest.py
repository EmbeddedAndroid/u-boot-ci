"""Read-only client of a LAVA server's REST API (v0.2) for public jobs:
job lists and job logs, without a token. Job records are reduced to an
allowlist of fields: a definition can carry artifact credentials, so it
is never returned."""
import gzip
import json
import os
import urllib.parse
import urllib.request

FIELDS = ("id", "description", "requested_device_type", "actual_device", "health", "state",
          "health_check", "end_time")


class LavaRest:
    def __init__(self, url, cache=None, opener=None):
        self.url = url.rstrip("/")
        self.cache = cache
        self._open = opener or (lambda u: urllib.request.urlopen(u, timeout=300))

    def _get(self, path, query=None):
        u = "%s/api/v0.2/%s" % (self.url, path)
        if query:
            u += "?" + urllib.parse.urlencode(query)
        with self._open(u) as r:
            return r.read()

    def jobs(self, limit=25, **filters):
        """Finished jobs matching the filters (LAVA REST field lookups),
        newest first."""
        q = {"ordering": "-id", "limit": limit, "state": "Finished"}
        q.update({k: v for k, v in filters.items() if v is not None})
        return [{k: j.get(k) for k in FIELDS} for j in json.loads(self._get("jobs/", q))["results"]]

    def log(self, job_id):
        """A finished job's log (the YAML lines LAVA serves), kept in the
        cache directory when there is one."""
        path = os.path.join(self.cache, "%d.yaml.gz" % int(job_id)) if self.cache else None
        if path and os.path.exists(path):
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return f.read()
        text = self._get("jobs/%d/logs/" % int(job_id)).decode("utf-8", "replace")
        if path:
            os.makedirs(self.cache, exist_ok=True)
            with gzip.open(path + ".tmp", "wt", encoding="utf-8") as f:
                f.write(text)
            os.replace(path + ".tmp", path)
        return text

    def job_url(self, job_id):
        return "%s/scheduler/job/%d" % (self.url, int(job_id))
