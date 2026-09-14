# Azure worker reboot persistence preparation

Date: 2026-09-14

Both live-test Azure hosts had `cashpilot-worker.service` corrected to use the
same Compose project and the pinned `1.50.18` override used by the running
container. `systemctl daemon-reload` completed without restarting the worker;
container ID, image, health, and `/data` volume remained unchanged.

This removes the previously observed reboot drift risk where the unit used the
`cashpilot-worker` project name and could create a second worker-data volume.
Actual host reboot persistence remains unverified and requires a separately
scheduled owner-approved reboot window.
