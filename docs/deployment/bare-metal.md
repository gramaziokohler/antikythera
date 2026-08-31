# Run on bare metal

Running the services directly on a machine, without Docker, is supported but takes more
work than [Run with Docker](docker.md) — which is what most installations should use.
Reach for bare metal when Docker is not an option: a locked-down lab machine, an existing
server with its own service management, or hardware access that a container makes awkward.

!!! note
    The layout below matches the production Antikythera server at ETH Zurich, which runs
    natively with apt-managed daemons and systemd units. The one place these instructions
    deliberately differ is installation: they install the released package from PyPI, where
    that server deploys from a git checkout. Corrections are welcome on the
    [issue tracker](https://github.com/gramaziokohler/antikythera/issues).

## What has to run

A complete installation is six processes. The MCP server is optional; the rest are not:

| Component | Provided by | Listens on |
| --- | --- | --- |
| Redis | `redis-server` | 6379 (localhost only) |
| MQTT broker | `mosquitto` | 1883, 8083 |
| Orchestrator | `antikythera` | 8000 (localhost only) |
| Built-in agents | `antikythera-agents run` | — |
| MCP server (optional) | `antikythera-mcp` | 8001 (localhost only) |
| Web UI | static files served by nginx | 80 / 443 |

The orchestrator, the agents and the MCP server all come from the same Python package; the
web UI is a separate build. Everything except nginx and the broker binds to localhost.

## Target platform

Written for **Ubuntu 24.04 LTS** on x86-64, with systemd; Debian 12 works the same way.
Any Linux with Python 3.12 and the packages below will do — adjust the package manager
commands.

Python 3.9 is the floor for the SDK, but run the server on **3.12**: that is what the
production deployment and the published container image use.

## 1. System packages

```bash
sudo apt update
sudo apt install -y \
  ca-certificates curl git \
  python3 python3-venv python3-pip \
  redis-server \
  mosquitto mosquitto-clients \
  nginx
```

Redis is fine with the packaged defaults: it binds to localhost and persists to
`/var/lib/redis`. Confirm it is up with `redis-cli ping`.

## 2. Configure the MQTT broker

Antikythera needs a plain TCP listener for agents and a WebSocket listener for browser
clients. Write `/etc/mosquitto/conf.d/antikythera.conf`:

```conf
listener 1883 0.0.0.0
allow_anonymous true

listener 8083
protocol websockets
allow_anonymous true

log_type error
log_type warning
log_type notice
```

Restart it and prove a message makes the round trip:

```bash
sudo systemctl restart mosquitto
systemctl is-active mosquitto
ss -tlnp | grep -E ':(1883|8083)\b'

mosquitto_sub -h 127.0.0.1 -p 1883 -t antikythera/healthcheck -C 1 -W 2 &
sleep 0.5
mosquitto_pub -h 127.0.0.1 -p 1883 -t antikythera/healthcheck -m ok
wait
```

This is anonymous MQTT with no TLS, matching what the container images do. See
[Security](#security) before putting it on anything but a trusted network.

## 3. Install Antikythera

Install the released package into a virtualenv owned by a dedicated service user:

```bash
sudo useradd --system --home /opt/antikythera --shell /usr/sbin/nologin antikythera
sudo mkdir -p /opt/antikythera
sudo chown antikythera:antikythera /opt/antikythera

sudo -u antikythera python3 -m venv /opt/antikythera/venv
sudo -u antikythera /opt/antikythera/venv/bin/pip install "antikythera-sdk[deployment]"
```

The `deployment` extra pulls in FastAPI, uvicorn, the Redis client and the MCP server —
everything the orchestrator needs beyond the SDK itself. The published wheel ships the
generated protobuf modules, so there is no code generation step.

Check that all three entry points work before writing any unit files:

```bash
/opt/antikythera/venv/bin/antikythera --help
/opt/antikythera/venv/bin/antikythera-agents --help
/opt/antikythera/venv/bin/antikythera-mcp --help
```

### Agent plugins

Agents ship as plugins, and some pull heavy third-party dependencies that are not
installed by default. The `moveit` agent, for example, imports `compas_fab`:

```bash
sudo -u antikythera /opt/antikythera/venv/bin/pip install compas-fab
```

Without it the launcher still starts, but plugin discovery logs a warning for every
plugin it could not import. Install the ones you need, or ignore the warnings for the
ones you do not.

## 4. Orchestrator service

The orchestrator reads its Redis and MQTT addresses from the environment. Write
`/etc/antikythera.env`:

```bash
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
MQTT_BROKER_HOST=127.0.0.1
MQTT_BROKER_PORT=1883
```

Then `/etc/systemd/system/antikythera-orchestrator.service`:

```ini
[Unit]
Description=Antikythera orchestrator
After=network-online.target redis-server.service mosquitto.service
Wants=network-online.target
Requires=redis-server.service mosquitto.service

[Service]
Type=simple
User=antikythera
WorkingDirectory=/opt/antikythera
EnvironmentFile=/etc/antikythera.env
ExecStart=/opt/antikythera/venv/bin/antikythera --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now antikythera-orchestrator
```

The orchestrator also writes an `orchestrator.log` into its working directory, in addition
to what journald captures.

## 5. Agents service

The built-in agents run as their own process.
`/etc/systemd/system/antikythera-agents.service`:

```ini
[Unit]
Description=Antikythera agents
After=network-online.target mosquitto.service antikythera-orchestrator.service
Wants=network-online.target
Requires=mosquitto.service antikythera-orchestrator.service

[Service]
Type=simple
User=antikythera
WorkingDirectory=/opt/antikythera
EnvironmentFile=/etc/antikythera.env
ExecStart=/opt/antikythera/venv/bin/antikythera-agents run \
    --broker-host 127.0.0.1 --broker-port 1883
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now antikythera-agents
```

This starts every agent registered in that virtualenv — the first-party `system.*`, `io.*`
and `user_interaction.*` types, plus any agent plugin you install alongside them. Add
`--sys-only` to restrict it to `system.*`, keeping in mind that a blueprint using any other
first-party type will then stall on a task no agent claims. Agents for your own hardware
normally run on other machines and connect to port 1883 over the network.

!!! warning
    `run` is a required subcommand. `antikythera-agents --sys-only ...` without it exits
    non-zero with usage text and never starts the launcher — a unit file written against
    the older CLI will fail on restart.

## 6. MCP server (optional)

Lets an LLM client author blueprints and drive sessions over the Model Context Protocol.
Write `/etc/systemd/system/antikythera-mcp.service`:

```ini
[Unit]
Description=Antikythera MCP SSE server
After=network-online.target antikythera-orchestrator.service
Wants=network-online.target
Requires=antikythera-orchestrator.service

[Service]
Type=simple
User=antikythera
WorkingDirectory=/opt/antikythera
Environment=ANTIKYTHERA_API_BASE=http://127.0.0.1:8000
ExecStart=/opt/antikythera/venv/bin/antikythera-mcp \
    --transport sse --host 127.0.0.1 --port 8001
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now antikythera-mcp
```

## 7. Web UI and nginx

The UI is a static bundle built from the
[antikythera-frontend](https://github.com/gramaziokohler/antikythera-frontend) repository.
It needs Node.js 22:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

```bash
git clone https://github.com/gramaziokohler/antikythera-frontend.git
cd antikythera-frontend
npm ci
npm run build

sudo mkdir -p /var/www/antikythera
sudo cp -a dist/. /var/www/antikythera/
```

The build bakes in the broker address the UI hands to the orchestrator when starting a
session. With everything on one server the default (`127.0.0.1`) is correct. If the broker
runs elsewhere, set it at build time — it must be the address the **orchestrator** uses to
reach the broker, not the address browsers use:

```bash
VITE_MQTT_BROKER_HOST=broker.example.lan VITE_MQTT_BROKER_PORT=1883 npm run build
```

Serve the bundle and proxy the API. The UI calls the orchestrator at the same origin under
`/api`, and the orchestrator sends no CORS headers, so this proxy is not optional.
Write `/etc/nginx/sites-available/antikythera`:

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    root /var/www/antikythera;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Session updates arrive as server-sent events on a long-lived connection.
        # Without these two, nginx buffers the stream and drops it after 60s.
        proxy_buffering off;
        proxy_read_timeout 24h;
    }

    # Only needed if MCP clients connect from outside the server.
    location /mcp/ {
        proxy_pass http://127.0.0.1:8001/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 24h;
    }

    location / {
        try_files $uri $uri.html $uri/ /index.html;
    }
}
```

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/antikythera /etc/nginx/sites-enabled/antikythera
sudo nginx -t && sudo systemctl reload nginx
```

## 8. TLS

For a server with a DNS name reachable on port 80, certbot configures nginx for you:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d antikythera.example.org
```

Choose the redirect option when prompted, so HTTP goes to HTTPS. Renewal is handled by the
certbot systemd timer the package installs.

```bash
sudo nginx -t
curl -I https://antikythera.example.org/
sudo systemctl list-timers | grep certbot
```

Certbot writes a second `server` block for port 443. Any `location` you added above lives
only in the block certbot copied it from — check that `/api/` and `/mcp/` are present in
the HTTPS block too, and re-add them if not.

!!! warning
    TLS encrypts the connection. It does not authenticate anyone. A server reachable from
    the public internet over HTTPS is still a server anyone can drive — see
    [Security](#security).

Browser clients that speak MQTT over WebSockets cannot reach `ws://host:8083` from an
HTTPS page. If you have such clients — the bundled UI is not one of them — proxy the
broker's WebSocket listener through nginx and point them at `wss://host/mqtt`:

```nginx
location /mqtt {
    proxy_pass http://127.0.0.1:8083;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400;
}
```

## Verifying

```bash
systemctl is-active antikythera-orchestrator antikythera-agents antikythera-mcp
ss -tlnp | grep -E ':(8000|8001)\b'

curl -fsS http://127.0.0.1:8000/docs >/dev/null && echo "orchestrator: ok"
curl -fsS http://127.0.0.1/ >/dev/null       && echo "frontend: ok"
curl -fsS http://127.0.0.1/api/docs >/dev/null && echo "api proxy: ok"
```

Diagnostics when one of those fails:

```bash
sudo journalctl -u antikythera-orchestrator -n 100 --no-pager
sudo journalctl -u antikythera-agents -n 100 --no-pager
sudo journalctl -u antikythera-mcp -n 100 --no-pager
```

Then open the server in a browser, upload a blueprint from `examples/`, and start it.

## Security

There is **no authentication** on the REST API and the broker accepts anonymous
connections. Anyone who can reach these ports can start, stop and delete sessions — and on
a machine driving real hardware, that is not a theoretical concern.

Expose ports 80/443 and 1883 to the local network only, and keep 8000, 8001 and 6379 on
localhost as the units above do. If access from outside is genuinely needed, put it behind
a VPN or an authenticating reverse proxy; TLS alone is not access control. A firewall rule
set worth starting from:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 80 proto tcp
sudo ufw allow from 192.168.0.0/16 to any port 443 proto tcp
sudo ufw allow from 192.168.0.0/16 to any port 1883 proto tcp
sudo ufw enable
```

## Updating

```bash
sudo -u antikythera /opt/antikythera/venv/bin/pip install --upgrade "antikythera-sdk[deployment]"
sudo systemctl restart antikythera-orchestrator antikythera-agents antikythera-mcp
```

Rebuild and redeploy the frontend bundle separately, from its own repository.
