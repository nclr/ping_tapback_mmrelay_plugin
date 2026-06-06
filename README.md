# ping_tapback_mmrelay_plugin

A custom plugin for [meshtastic-matrix-relay](https://github.com/jeremiah-k/meshtastic-matrix-relay) that reacts to Meshtastic messages with emoji tapbacks and supports running traceroutes from Matrix.

## Features

### Hop-count tapback

When a node sends a message containing a trigger word, the plugin responds with a tapback emoji showing how many hops the message traveled.

| Trigger words | Response |
|---|---|
| `ping`, `test`, `hello` | hop-count emoji (0️⃣–8️⃣) |
| `πίνγκ`, `τέστ` (Greek) | hop-count emoji |
| `καλημέρα` / `kalimera` | ☀️ |
| `καληνύχτα` / `kalinixta` / `good night` | 🌙 |

The tapback is sent as a **reaction** to the original message (using `reply_id` + `emoji=1`), so it appears as a reaction bubble in Meshtastic clients that support it rather than as a new message.

### Traceroute from Matrix

Send `!traceroute <node>` in a Matrix room to trigger a traceroute to any node in the mesh. You can pass either a hex node ID (`!abcd1234`) or a short name, which is resolved against the current node list. The plugin replies with the full route and SNR values for each hop, in both directions.

**Example:**
```
!traceroute !abcd1234
!traceroute MN1
```

Before running, it acknowledges with a descriptive status line including the target's long name, short name, and ID. When the node has a known last position and/or was heard recently, it also adds an OpenStreetMap link to its coordinates and a "last heard" timestamp:
```
🔍 Running traceroute to MyNode (MN1) `!abcd1234`…
📍 37.97640, 23.72784 — [OpenStreetMap](https://www.openstreetmap.org/?mlat=37.97640&mlon=23.72784#map=15/37.97640/23.72784)
🕒 Last heard: 2026-06-06 13:37 UTC (12m ago)
```
The 📍 and 🕒 lines are only included when that data is available for the node; otherwise the status message falls back to just the first line.

**Response:**
```
Towards destination: !relay → !abc123 (1.5 dB) → !abcd1234 (3.25 dB)

Back to us: !abcd1234 → !abc123 (1.75 dB) → !relay (2.5 dB)
```

Hops with no SNR data are shown as `? dB (unknown SNR)`.

The traceroute runs in the background so the plugin stays responsive to other commands while waiting for the result (up to a 90-second timeout).

**Multi-hop handling:** the underlying meshtastic `onResponse` callback is a one-shot handler that gets consumed by the first packet referencing the request — typically an early `ROUTING_APP` ack on multi-hop routes — which previously caused replies from nodes more than one hop away to be lost. To work around this, the plugin also listens on meshtastic's general receive bus and matches the genuine `TRACEROUTE_APP` reply by portnum and source node, so multi-hop traceroutes report reliably.

## Installation

Place the plugin folder in your mmrelay custom plugins directory (typically `~/.mmrelay/plugins/custom/ping_tapback/`) and enable it in your mmrelay config:

```yaml
custom-plugins:
  ping_tapback:
    active: true
```

## Configuration

The plugin respects the standard mmrelay channel and direct message settings. Enable it per-channel in your `matrix_rooms` config as you would any other plugin.
