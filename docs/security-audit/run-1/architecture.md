# Architecture reconnaissance

CashPilot is a self-hosted FastAPI dashboard/orchestrator for passive-income and
bandwidth-sharing providers. Browser operators use the UI; owner/writer/reader
roles manage credentials, providers, proxy pools, payouts, and fleet workers.
Workers report authenticated heartbeats and receive provider/container commands.

The stack is Python/FastAPI/Uvicorn, Jinja2 plus static JavaScript, aiosqlite
SQLite, Fernet-encrypted credentials, signed session cookies, httpx,
APScheduler, Prometheus metrics, and Docker. The UI runs on port 8080 and the
worker API on 8081. Compose publishes UI loopback by default; the worker mounts
the Docker socket and therefore has host-level operational authority by design.

Trust boundaries include browser HTTP, remote worker HTTP, Unix helper sockets,
environment/config files, YAML service catalogs, provider APIs, Docker socket,
and the encrypted database/key files. Main entry points are
`app/main.py`, `app/worker_api.py`, `app/auth.py`, `app/deps.py`,
`app/database.py`, `app/routers/`, and `app/static/js/app.js`.

Input surfaces include authenticated provider/account/wallet/proxy imports,
worker heartbeats and command APIs, runtime asset and chain restore requests,
proxy metadata/import files, environment variables, and external provider API
responses. Dangerous sinks include Docker orchestration/exec, bounded SSH and
subprocess wrappers, tar creation/restoration, SQL migrations, and DOM
`innerHTML`; source uses authorization guards, path allowlists, escaping helpers,
bounded subprocess calls, and encrypted secret storage at these boundaries.

Comparable baseline: `money4band`, named in the project README. CashPilot is
more fleet-centric and adds provider-specific collectors, proxy leasing, and
worker capability gates.
