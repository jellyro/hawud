# Home Assistant Integration For What's Up Docker

A Home Assistant custom integration that connects to a [What's Up Docker (WUD)](https://getwud.github.io/wud/) instance and exposes Docker container updates as native Update entities in Home Assistant.

## Requirements

- Home Assistant 2026.6.0 or newer
- A running [WUD](https://getwud.github.io/wud/) instance accessible from Home Assistant

## Installation (HACS)

1. In Home Assistant, open HACS > Integrations > Settings > Custom repositories
2. Add this repository URL and select category Integration
3. Click Download
4. Restart Home Assistant

## Configuration

Go to Settings > Devices and Services > Add Integration and search for What's Up Docker Integration.

| Field | Required | Description |
|---|---|---|
| WUD URL | Yes | Base URL of your WUD instance, e.g. http://192.168.1.10:3000 or https://wud.example.com |
| Instance name | No | Friendly name to identify this WUD instance and prefix its entities, e.g. Home Server |
| Username | No | WUD basic auth username |
| Password / Token | No | WUD basic auth password or API token |
| Verify TLS certificate | Yes | Disable for self-signed certs behind a reverse proxy |
| Poll interval | Yes | How often to check for updates in seconds, default 300 |

The poll interval and max concurrent updates can be changed later via Settings > Devices and Services > What's Up Docker Integration > Configure.

## Recommended Setup

The recommended approach is to run your containers with Docker Compose and let Home Assistant manage when updates are applied.

1. Run your containers with Docker Compose.
2. In WUD, configure a Compose trigger for each container. This allows WUD to recreate a container with the new image when asked.
3. Do not enable auto-update in WUD itself. Instead, use the Auto update switch entities provided by this integration to control which containers update automatically and when.

This gives you full control from Home Assistant. You can target specific containers, create automations with conditions, set a daily maintenance window using the Auto update time entity, limit how many containers update at the same time, and get notified through standard HA notification channels.

## Entities

Each discovered container creates a device with four entities.

| Entity | Type | Description |
|---|---|---|
| update.[name] | Update | Shows installed vs. latest version and supports Install |
| button.[name]_check_for_updates | Button | Asks WUD to re-check for a newer image immediately |
| switch.[name]_auto_update | Switch | When on, automatically installs available updates |
| time.[name]_auto_update_time | Time | Optional daily time at which auto-updates are triggered |

### Auto update behavior

The auto-update switch and optional time entity work together per container.

- Switch off: no automatic action is taken. Updates are shown in the Update entity but not applied.
- Switch on, no time set: the update is triggered on the next poll after it is detected.
- Switch on, time set: the update is triggered only at or after the configured time on the day it is detected. If the poll runs before that time, the update waits until the next poll after the scheduled time.

Each version is only triggered once per container. If a new version becomes available after an update, the switch triggers again for the new version. When a time is configured, the switch also triggers again on the next day if the container still reports an update.

State is preserved across Home Assistant restarts.

### Max concurrent updates

In the options dialog (Configure), you can set a limit on how many containers are updated at the same time. The default is 0, which means no limit. When the limit is reached, further updates are queued and run as slots become available. This is useful to avoid restarting too many services simultaneously.

### Update entity attributes

| Attribute | Description |
|---|---|
| watcher | WUD watcher name monitoring this container |
| container_id | WUD internal container ID |
| image_name | Docker image name |
| image_tag | Currently running image tag |
| image_digest | Currently running image digest |
| registry | Container registry URL |
| new_tag | New tag available when an update exists |
| new_digest | New digest available when an update exists |
| last_checked | Timestamp of the last WUD update check |

## How it works

- The integration polls GET /api/containers on the configured interval.
- Containers are identified by the combination of watcher name and container name.
- Clicking Install on an Update entity fetches the triggers configured in WUD for that container, runs the first docker or compose trigger, and falls back to other triggers or a watch refresh if none are configured.
- Pressing Check for updates calls POST /api/containers/{id}/watch and refreshes that specific container immediately without waiting for the next poll.
- The integration never talks to Docker directly. All actions go through the WUD API.

## Notes

- To have Install actually update a container, configure a Docker or Compose trigger in WUD for that container. Without one, Install only triggers a watch refresh.
- If you run multiple WUD instances, give each a unique Instance name during setup to keep entities clearly separated.

## Attribution

This is a third-party Home Assistant integration for [What's Up Docker](https://github.com/fmartinou/whats-up-docker).

WUD is developed by [Manfred Martin](https://github.com/fmartinou) and is licensed under the [MIT License](https://github.com/fmartinou/whats-up-docker/blob/master/LICENSE).

This integration is not affiliated with or endorsed by the WUD project.
