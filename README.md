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

The tapback is sent as a **reaction** to the original message (using `reply_id` + `emoji=1`), so it appears as a reaction bubble in Meshtastic clients that support it rather than as a new message.

### Traceroute from Matrix

Send `!traceroute <nodeId>` in a Matrix room to trigger a traceroute to any node in the mesh. The plugin replies with the full route and SNR values for each hop.

**Example:**
```
!traceroute !abcd1234
```

**Response:**
```
Towards destination: !relay → !abc123 (1.5 dB) → !abcd1234 (3.25 dB)
Back to us: !abcd1234 → !abc123 (1.75 dB) → !relay (2.5 dB)
```

The traceroute runs in the background so the plugin stays responsive to other commands while waiting for the result.

## Installation

Place the plugin folder in your mmrelay custom plugins directory (typically `~/.mmrelay/plugins/custom/ping_tapback/`) and enable it in your mmrelay config:

```yaml
custom-plugins:
  ping_tapback:
    active: true
```

## Configuration

The plugin respects the standard mmrelay channel and direct message settings. Enable it per-channel in your `matrix_rooms` config as you would any other plugin.
