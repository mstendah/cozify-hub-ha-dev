# Cozify Hub API Documentation

Document revision: `0.9`

Document date: `2026-10-01`

## Changelog

| Revision | Date | Changes |
| --- | --- | --- |
| `0.9` | `2026-10-01` | Documented `NEW_CAP`. |
| `0.8` | `2026-09-23` | Something else. |

### 6.1 Hub feature codes

<table>
<thead><tr><th>Code</th><th>Name</th><th>Explanation</th><th>Example value</th></tr></thead>
<tbody>
<tr><td><code>2</code> (<code>0x02</code>)</td><td><code>CUSTOM_RULES</code></td><td>Custom rule support.</td><td><code>2</code></td></tr>
<tr><td><code>20</code> (<code>0x14</code>)</td><td><code>SPOT_PRICES</code></td><td>Spot.</td><td><code>20</code></td></tr>
</tbody></table>

### 6.7 Device capabilities

<table>
<thead><tr><th>Capability</th><th>Capability description</th><th>Attribute identifier</th><th>Attribute description</th><th>Type and allowed values</th></tr></thead>
<tbody>
<tr><td><code>ON_OFF</code></td><td>Device can be turned on / off</td><td><code>state.isOn</code></td><td>—</td><td>boolean<br>writable</td></tr>
<tr><td><code>CONTROL_TEMPERATURE</code></td><td>Device can control temperature</td><td><code>state.targetTemp</code></td><td>—</td><td>float Celsius<br>writable</td></tr>
<tr><td></td><td></td><td><code>state.heatingDemand</code></td><td>Heating power in use</td><td>float [0.0, 1.0]<br>read-only</td></tr>
<tr><td><code>SHUTTER</code></td><td>Device controls curtains</td><td><code>state.motorStatus</code></td><td>Current motor direction.</td><td><table><thead><tr><th>Value</th><th>Meaning</th></tr></thead><tbody><tr><td><code>-1</code></td><td>Motor down</td></tr><tr><td><code>0</code></td><td>Stopped</td></tr></tbody></table></td></tr>
<tr><td><code>NEW_CAP</code></td><td>A brand new thing</td><td><code>state.newValue</code></td><td>—</td><td>int Percent<br>read-only</td></tr>
</tbody></table>

### 6.8 Device data

#### 5.2.1 `GET /devices`

**Access:** `GUEST_ACCESS`

#### 5.2.4 `PUT /devices/command`

**Access:** `GUEST_ACCESS`

```json
{"type": "CMD_DEVICE_ON", "id": "x"}
```
