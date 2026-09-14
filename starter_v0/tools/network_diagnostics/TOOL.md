---
name: network_diagnostics
track: bonus
kind: local_status
provider: mock_network_diagnostics
requires_env: []
inputs: [asset_id]
outputs: [diagnostics]
side_effect: false
---
# network_diagnostics

Looks up one company asset and returns its current network diagnostics, including IP address, ping status, DNS resolution, and VPN status. A valid asset ID is required.
