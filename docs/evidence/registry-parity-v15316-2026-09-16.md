# Registry/runtime parity (v1.53.16)

Verified from the images actually running in production scope.

| Role | Runtime tag | Baked version | Runtime digest | Platform |
| --- | --- | --- | --- | --- |
| UI | `ghcr.io/assetforgeai-tech/cashpilot:1.53.16` | `1.53.16` | `sha256:16439fa9c7e6e378cee2d59b252a95f75b6ff77e929fec7e3e5684dc2a8a5e09` | `linux/amd64` |
| Worker (both Azure hosts) | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.53.16` | `1.53.16` | `sha256:681e496bd188a19d9301d7f1e426dc68431b13f5a3e2518b0e62ed6d3aaf9473` | `linux/amd64` |

UI and worker containers were `running|healthy`; both workers resolved to the
same worker digest. The runtime tag, embedded `CASHPILOT_VERSION`, and deployed
role agree. This proves parity for the deployed amd64 artifacts; the release
workflow separately verifies every published multi-arch tag.
