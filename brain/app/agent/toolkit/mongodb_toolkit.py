# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

"""Read-only MongoDB query toolkit.

Drives the ``mongosh`` CLI in a subprocess (the same local-CLI style as
``GitToolkit``) so an agent can look something up directly in a MongoDB
cluster -- find a document, count a cohort, confirm a write landed --
without booting the app or an ORM. This turns the ad-hoc repro recipe in
``mongodb-toolkit.md`` into a repeatable, guard-railed toolkit.

Safety rules:
  * Read-only. The named tools only ever issue ``find`` / ``countDocuments``
    / ``distinct`` / read-only ``aggregate``; the free-form escape hatch
    (``mongo_eval``) is rejected by a write guard before anything runs.
  * The connection string is loaded but never printed -- every output and
    error path redacts it.
  * The default database is ``dev`` (override with ``MONGO_DB`` or the
    per-call ``database=`` argument).
  * Reads use the URI's own read preference; pass ``primary=True`` for
    write-following checks that must not read a stale secondary.

Enabled only when a connection string is resolvable: ``MONGO_URL`` (or
``MONGODB_URI`` / ``MONGO_URI``), else the ``mongodb`` key of the JSON file
named by ``MONGO_CONFIG``. ``get_can_use_tools`` returns ``[]`` otherwise,
so the agent stays Mongo-free until a URL is configured.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from camel.toolkits import BaseToolkit
from camel.toolkits.function_tool import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.component.environment import env
from app.service.task import Agents

logger = logging.getLogger("mongodb_toolkit")

#: Env vars that may hold the connection string, in priority order.
_URL_ENV_KEYS = ("MONGO_URL", "MONGODB_URI", "MONGO_URI")

#: Tools that accept a free-form script / aggregation pipeline rather than a
#: fixed read verb. The assembler gates these under Ask mode, and the write
#: guard below still refuses mutating content inside them.
WRITE_TOOL_NAMES = {"mongo_eval"}

#: Write methods / stages that mean "this mutates". Used to refuse free-form
#: scripts. Matches a write verb followed by a call, so ``db.people.deleteMany(
#: {...})`` and ``.insertOne(`` are caught while a *field* named ``updatedAt``
#: (no trailing paren) is not. Plus the aggregating ``$out`` / ``$merge`` stages.
_WRITE_GUARD = re.compile(
    r"(?:^|[^\w])(?:insert|update|replace|delete|remove|drop|rename|save|"
    r"bulkWrite|findOneAnd\w*|findAndModify|createIndex|dropIndex|"
    r"createCollection|mapReduce)\w*\s*\(|\$out\b|\$merge\b",
    re.IGNORECASE,
)

#: Matches any Mongo connection string so it can be scrubbed from output.
_URI_PATTERN = re.compile(r"mongodb(?:\+srv)?://[^\s'\"`]+")

#: Wraps a 24-hex string filter on ``_id`` in ``ObjectId()`` so callers can
#: pass ``{"_id":"692d58ab..."}`` as plain JSON. Relies on ``filter`` being in
#: scope (every caller that includes it defines ``const filter = ...`` first).
_OBJECTID_PRELUDE = (
    "for (const k of Object.keys(filter)) { "
    "if (k === '_id' && typeof filter[k] === 'string' && "
    "/^[0-9a-f]{24}$/i.test(filter[k])) filter[k] = ObjectId(filter[k]); }\n"
)

#: Cap output so a huge result set can't blow the model context.
_MAX_OUTPUT_CHARS = 20_000

#: Cap documents returned per call.
_MAX_DOCS = 200


def resolve_connection_string() -> str | None:
    """Resolve the Mongo connection string from env or a JSON config file.

    Reads ``MONGO_URL`` / ``MONGODB_URI`` / ``MONGO_URI`` first; if none is
    set, reads the ``mongodb`` key of the JSON file named by ``MONGO_CONFIG``
    (e.g. a server's ``config/default.json``). Returns ``None`` when nothing
    is configured. The value is never logged.
    """
    for key in _URL_ENV_KEYS:
        value = (env(key) or "").strip()
        if value:
            return value
    config_path = (env("MONGO_CONFIG") or "").strip()
    if not config_path:
        return None
    try:
        data = json.loads(Path(config_path).expanduser().read_text())
    except (OSError, ValueError) as exc:
        logger.warning("MONGO_CONFIG could not be read: %s", exc)
        return None
    value = str(data.get("mongodb") or "").strip()
    return value or None


def redact(text: str) -> str:
    """Scrub any Mongo connection string out of ``text``."""
    return _URI_PATTERN.sub("mongodb+srv://<redacted>", text or "")


class MongoDBToolkit(BaseToolkit, AbstractToolkit):
    """Read-only MongoDB access through the ``mongosh`` CLI."""

    agent_name: str = Agents.developer_agent

    def __init__(
        self,
        api_task_id: str,
        agent_name: str | None = None,
        timeout: float | None = 30.0,
        mongosh_path: str | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self.api_task_id = api_task_id
        if agent_name is not None:
            self.agent_name = agent_name
        self.mongosh_path = (
            mongosh_path or (env("MONGOSH_PATH") or "mongosh").strip()
        )

    @classmethod
    def get_can_use_tools(cls, api_task_id: str) -> list[FunctionTool]:
        # No connection string -> no tools. Keeps the agent Mongo-free until a
        # URL is configured (mirrors GithubToolkit's token gate).
        if resolve_connection_string():
            return cls(api_task_id).get_tools()
        return []

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _default_database(self) -> str:
        return (env("MONGO_DB") or "dev").strip() or "dev"

    def _db_prefix(self, database: str) -> str:
        """JS that switches the shell to ``database`` (or the default)."""
        name = (database or "").strip() or self._default_database()
        return f"db = db.getSiblingDB({json.dumps(name)});\n"

    def _run_js(
        self,
        script: str,
        *,
        primary: bool = False,
        guard: bool = False,
    ) -> str:
        """Run ``script`` in mongosh; return printed output, redacted.

        ``guard`` enables the write guard for free-form scripts. Output and
        every error path have the connection string stripped.
        """
        uri = resolve_connection_string()
        if not uri:
            return (
                "[mongo error]: no connection string configured; set "
                "MONGO_URL (or MONGODB_URI / MONGO_URI)."
            )
        if guard:
            match = _WRITE_GUARD.search(script)
            if match:
                return (
                    "[mongo error]: refused -- the script looks like a write "
                    f"('{match.group(0)}'). This toolkit is read-only."
                )
        prelude = (
            "db.getMongo().setReadPref('primary');\n" if primary else ""
        )
        full_script = prelude + script
        try:
            result = subprocess.run(
                [self.mongosh_path, uri, "--quiet", "--eval", full_script],
                capture_output=True,
                text=True,
                timeout=self.timeout or 30.0,
            )
        except FileNotFoundError:
            return (
                f"[mongo error]: '{self.mongosh_path}' is not installed or "
                "not on PATH (try: brew install mongosh)."
            )
        except subprocess.TimeoutExpired:
            return "[mongo error]: query timed out."
        except Exception as exc:  # pragma: no cover - defensive
            return f"[mongo error]: {redact(str(exc))}"

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            return f"[mongo error]: {redact(stderr or stdout)}"
        if not stdout:
            return f"[mongo error]: {redact(stderr or 'no output')}"
        if len(stdout) > _MAX_OUTPUT_CHARS:
            stdout = stdout[:_MAX_OUTPUT_CHARS] + "\n... (truncated)"
        return redact(stdout)

    # ------------------------------------------------------------------ #
    # Read tools
    # ------------------------------------------------------------------ #

    def mongo_list_collections(self, database: str = "") -> str:
        """List the collections in a database.

        Args:
            database (str): Database name; empty uses the default (dev).

        Returns:
            str: JSON with the database name and its sorted collections.
        """
        script = (
            self._db_prefix(database)
            + "print(EJSON.stringify({db: db.getName(), "
            "collections: db.getCollectionNames().sort()}, null, 2));"
        )
        return self._run_js(script)

    def mongo_find(
        self,
        collection: str,
        filter: str = "{}",
        projection: str = "{}",
        sort: str = "{}",
        limit: int = 5,
        database: str = "",
        primary: bool = False,
    ) -> str:
        """Find documents in a collection and return them as JSON.

        Args:
            collection (str): Collection name (required).
            filter (str): JSON query filter, e.g. ``{"kyc.status":"success"}``.
                A 24-hex ``_id`` string is wrapped in ``ObjectId()``.
            projection (str): JSON projection, e.g. ``{"name":1}``.
            sort (str): JSON sort, e.g. ``{"createdAt":-1}``.
            limit (int): Max documents to return (default 5, capped at 200).
            database (str): Database name; empty uses the default (dev).
            primary (bool): Read from the primary instead of the URI's (often
                secondary) read preference.

        Returns:
            str: JSON with db, collection, count and documents, or a
            redacted error.
        """
        name = (collection or "").strip()
        if not name:
            return "[mongo error]: a collection name is required."
        count = max(1, min(int(limit), _MAX_DOCS))
        coll = json.dumps(name)
        script = (
            self._db_prefix(database)
            + "const filter = " + (filter or "{}") + ";\n"
            + _OBJECTID_PRELUDE
            + f"const docs = db.getCollection({coll})"
            + f".find(filter, {projection or '{}'})"
            + f".sort({sort or '{}'})"
            + f".limit({count}).toArray();\n"
            + "print(EJSON.stringify({db: db.getName(), collection: "
            + f"{coll}, count: docs.length, docs: docs}}, null, 2));"
        )
        return self._run_js(script, primary=primary)

    def mongo_count(
        self,
        collection: str,
        filter: str = "{}",
        database: str = "",
        primary: bool = False,
    ) -> str:
        """Count documents matching a filter.

        Args:
            collection (str): Collection name (required).
            filter (str): JSON query filter (default matches all).
            database (str): Database name; empty uses the default (dev).
            primary (bool): Read from the primary read preference.

        Returns:
            str: JSON with db, collection and the count, or a redacted error.
        """
        name = (collection or "").strip()
        if not name:
            return "[mongo error]: a collection name is required."
        coll = json.dumps(name)
        script = (
            self._db_prefix(database)
            + "const filter = " + (filter or "{}") + ";\n"
            + _OBJECTID_PRELUDE
            + f"const n = db.getCollection({coll}).countDocuments(filter);\n"
            + "print(EJSON.stringify({db: db.getName(), collection: "
            + f"{coll}, count: n}}, null, 2));"
        )
        return self._run_js(script, primary=primary)

    def mongo_distinct(
        self,
        collection: str,
        field: str,
        filter: str = "{}",
        limit: int = 100,
        database: str = "",
    ) -> str:
        """List the distinct values of a field.

        Args:
            collection (str): Collection name (required).
            field (str): Field to take distinct values of (required).
            filter (str): JSON query filter (default matches all).
            limit (int): Max values to return (default 100, capped at 200).
            database (str): Database name; empty uses the default (dev).

        Returns:
            str: JSON with db, collection, field, count and values, or a
            redacted error.
        """
        name = (collection or "").strip()
        if not name:
            return "[mongo error]: a collection name is required."
        field = (field or "").strip()
        if not field:
            return "[mongo error]: a field name is required."
        cap = max(1, min(int(limit), _MAX_DOCS))
        coll = json.dumps(name)
        script = (
            self._db_prefix(database)
            + "const filter = " + (filter or "{}") + ";\n"
            + _OBJECTID_PRELUDE
            + f"const v = db.getCollection({coll})"
            + f".distinct({json.dumps(field)}, filter);\n"
            + "print(EJSON.stringify({db: db.getName(), collection: "
            + f"{coll}, field: {json.dumps(field)}, count: v.length, "
            + f"values: v.slice(0, {cap})}}, null, 2));"
        )
        return self._run_js(script)

    def mongo_aggregate(
        self,
        collection: str,
        pipeline: str = "[]",
        limit: int = 50,
        database: str = "",
        primary: bool = False,
    ) -> str:
        """Run a read-only aggregation pipeline.

        ``$out`` / ``$merge`` stages (which write) are refused by the guard.

        Args:
            collection (str): Collection name (required).
            pipeline (str): JSON aggregation pipeline, e.g.
                ``[{"$group":{"_id":"$kyc.status","n":{"$sum":1}}}]``.
            limit (int): Max result documents (default 50, capped at 200).
            database (str): Database name; empty uses the default (dev).
            primary (bool): Read from the primary read preference.

        Returns:
            str: JSON with db, collection, count and documents, or a
            redacted error.
        """
        name = (collection or "").strip()
        if not name:
            return "[mongo error]: a collection name is required."
        cap = max(1, min(int(limit), _MAX_DOCS))
        coll = json.dumps(name)
        # mongosh's aggregation cursor has no ``.limit()`` (unlike find); cap
        # the result with a trailing ``$limit`` stage instead.
        script = (
            self._db_prefix(database)
            + "const pipeline = " + (pipeline or "[]") + ";\n"
            + f"pipeline.push({{$limit: {cap}}});\n"
            + f"const docs = db.getCollection({coll})"
            + ".aggregate(pipeline).toArray();\n"
            + "print(EJSON.stringify({db: db.getName(), collection: "
            + f"{coll}, count: docs.length, docs: docs}}, null, 2));"
        )
        return self._run_js(script, primary=primary, guard=True)

    def mongo_find_by_id(
        self,
        object_id: str,
        collections: str = "people,users",
        database: str = "",
    ) -> str:
        """Look up an ``_id`` across several collections and report where it hit.

        A miss is not proof the data is missing: this prints how many matches
        each collection had, so a zero reads as "not in these collections"
        rather than "does not exist". Say which DB and collections you checked.

        Args:
            object_id (str): The 24-character hex ObjectId to look up.
            collections (str): Comma-separated collection names to check
                (default ``people,users``).
            database (str): Database name; empty uses the default (dev).

        Returns:
            str: JSON with db, id, the collections checked and per-collection
            match counts, or a redacted error.
        """
        oid = (object_id or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{24}", oid):
            return (
                "[mongo error]: object_id must be a 24-character hex string."
            )
        names = [
            c.strip() for c in (collections or "").split(",") if c.strip()
        ]
        if not names:
            return "[mongo error]: at least one collection is required."
        script = (
            self._db_prefix(database)
            + f"const oid = {json.dumps(oid)};\n"
            + f"const names = {json.dumps(names)};\n"
            + "const found = {};\n"
            + "for (const c of names) { found[c] = "
            "db.getCollection(c).countDocuments({_id: ObjectId(oid)}); }\n"
            + "print(EJSON.stringify({db: db.getName(), id: oid, "
            "checked: names, found: found}, null, 2));"
        )
        return self._run_js(script)

    def mongo_eval(
        self,
        script: str,
        database: str = "",
        primary: bool = False,
    ) -> str:
        """Run a free-form read-only mongosh script (escape hatch).

        Prefer the named tools; reach for this only for a query shape they
        don't cover. The write guard still applies: a script containing
        insert/update/delete/drop/... or an aggregation ``$out`` / ``$merge``
        stage is refused. Use ``print(...)`` to emit JSON.

        Args:
            script (str): JavaScript run in mongosh.
            database (str): Database name; empty uses the default (dev).
            primary (bool): Read from the primary read preference.

        Returns:
            str: Whatever the script prints, or a redacted error.
        """
        if not (script or "").strip():
            return "[mongo error]: a script is required."
        return self._run_js(
            self._db_prefix(database) + script,
            primary=primary,
            guard=True,
        )

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def get_tools(self) -> list[FunctionTool]:
        # kwargs_tolerant drops stray kwargs (name/signature preserved via
        # @wraps), so these tools survive any harness's calling convention.
        from app.utils.listen.toolkit_listen import kwargs_tolerant

        return [
            FunctionTool(kwargs_tolerant(self.mongo_list_collections)),
            FunctionTool(kwargs_tolerant(self.mongo_find)),
            FunctionTool(kwargs_tolerant(self.mongo_count)),
            FunctionTool(kwargs_tolerant(self.mongo_distinct)),
            FunctionTool(kwargs_tolerant(self.mongo_aggregate)),
            FunctionTool(kwargs_tolerant(self.mongo_find_by_id)),
            FunctionTool(kwargs_tolerant(self.mongo_eval)),
        ]
