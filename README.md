# What's Up Docker — Home Assistant Integration

A Home Assistant custom integration that connects to a [What's Up Docker (WUD)](https://getwud.github.io/wud/) instance and exposes Docker container updates as native **Update** entities.

## Requirements

- Home Assistant **2026.6.0** or newer
- A running [WUD](https://getwud.github.io/wud/) instance accessible from Home Assistant

## Installation (HACS)

1. In Home Assistant, open **HACS → Integrations → ⋮ → Custom repositories**
2. Add this repository URL and select category **Integration**
3. Click **Download**
4. Restart Home Assistant

## Configuration

Go to **Settings → Devices & Services → Add Integration** and search for **What's Up Docker Integration**.

| Field | Required | Description |
|---|---|---|
| WUD URL | Yes | Base URL, e.g. `http://192.168.1.10:3000` or `https://wud.example.com` |
| Instance name | No | Friendly name to identify this WUD instance and prefix all its entities, e.g. `Home Server` → entities become `update.home_server_freshrss` |
| Username | No | WUD basic auth username |
| Password / Token | No | WUD basic auth password or API token |
| Verify TLS certificate | Yes | Disable for self-signed certs behind a reverse proxy |
| Poll interval | Yes | How often to check for updates (seconds, default 300) |

The poll interval can be changed later via **Settings → Devices & Services → What's Up Docker Integration → Configure**.

## Entities

Each discovered container creates a **device** with two entities:

| Entity | Type | Description |
|---|---|---|
| `update.<name>` | Update | Shows current vs. latest version; supports Install |
| `button.<name>_check_for_updates` | Button | Immediately asks WUD to re-check for a newer image |

### Update entity attributes

In addition to the standard update entity fields, each entity exposes the following state attributes:

| Attribute | Description |
|---|---|
| `watcher` | WUD watcher name monitoring this container |
| `container_id` | WUD's internal container ID |
| `image_name` | Docker image name |
| `image_tag` | Currently running image tag |
| `image_digest` | Currently running image digest |
| `registry` | Container registry URL |
| `new_tag` | New tag available (when an update exists) |
| `new_digest` | New digest available (when an update exists) |
| `last_checked` | Timestamp of the last WUD update check |

## How it works

- The integration polls `GET /api/containers` on the configured interval.
- Containers are identified by `{watcher}_{name}` — a stable key that survives container recreations and WUD restarts, preventing duplicate or orphaned entities.
- Clicking **Install** on an Update entity:
  1. Fetches the triggers configured for that container in WUD.
  2. Runs the first `docker` or `compose` trigger (which actually recreates the container with the new image).
  3. Falls back to any other configured trigger, or a watch refresh if no triggers exist.
- Pressing the **Check for updates** button calls `POST /api/containers/{id}/watch` on WUD and immediately refreshes the coordinator.
- The integration never talks to Docker directly — all actions go through WUD.

## Notes

- To have the Install button actually update a container, configure a **Docker** or **Compose** trigger in WUD for that container.
- Without a trigger, Install triggers a watch refresh (re-checks for updates) but does not update the container.
- If you run multiple WUD instances, give each a unique **Instance name** during setup to keep entities clearly separated.
