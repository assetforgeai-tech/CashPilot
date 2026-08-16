"""EarnApp QEMU guest runtime."""

from __future__ import annotations

import secrets
import textwrap
import uuid as uuidlib
from dataclasses import dataclass


@dataclass(frozen=True)
class EarnAppQemuIdentity:
    hostname: str
    uuid: str
    serial: str
    mac: str
    machine_id: str
    product: str


def new_identity(prefix: str = "earnapp") -> EarnAppQemuIdentity:
    clean = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in prefix.lower()).strip("-") or "earnapp"
    return EarnAppQemuIdentity(
        hostname=f"{clean}-{secrets.token_hex(3)}",
        uuid=str(uuidlib.uuid4()),
        serial=secrets.token_hex(12).upper(),
        mac="52:54:%02x:%02x:%02x:%02x" % tuple(secrets.randbelow(256) for _ in range(4)),
        machine_id=secrets.token_hex(16),
        product=f"CP-{secrets.token_hex(4).upper()}",
    )


def render_qemu_command(identity: EarnAppQemuIdentity) -> str:
    user_data = textwrap.dedent(
        r"""
        #cloud-config
        hostname: __HOSTNAME__
        manage_etc_hosts: true
        package_update: true
        packages:
          - ca-certificates
          - curl
          - wget
          - openssl
        write_files:
          - path: /etc/machine-id
            permissions: '0444'
            content: "__MACHINE_ID__\n"
          - path: /root/install_earnapp_fixed.sh
            permissions: '0700'
            content: |
              #!/usr/bin/env bash
              set -euo pipefail
              systemctl stop earnapp earnapp_upgrader 2>/dev/null || true
              systemctl disable earnapp earnapp_upgrader 2>/dev/null || true
              rm -f /etc/systemd/system/earnapp*.service /usr/bin/earnapp /usr/bin/earnapp_bak /tmp/earnapp_*
              rm -rf /etc/earnapp /var/lib/earnapp /opt/earnapp /root/.earnapp
              systemctl daemon-reload
              update-ca-certificates --fresh
              wget -qO /tmp/earnapp.sh https://brightdata.com/static/earnapp/install.sh
              env SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt bash /tmp/earnapp.sh -y
              UUID="$(cat /etc/earnapp/uuid)"
              SERIAL="$(sha1sum /etc/machine-id | awk '{print $1}')"
              curl -fsS -H 'Content-Type: application/json' "https://client.earnapp.com/install_device?uuid=${UUID}&version=1.651.510&arch=x64&appid=node_earnapp.com&os=Ubuntu" --data "{\"serial\":\"${SERIAL}\"}"
              curl -fsS 'https://earnapp.com/dashboard/api/link_device' \
                -X POST \
                -H 'accept: application/json, text/plain, */*' \
                -H 'content-type: application/json' \
                -H 'origin: https://earnapp.com' \
                -H "referer: https://earnapp.com/dashboard/link/$UUID" \
                -H 'user-agent: Mozilla/5.0' \
                -H "csrf-token: $XSRF_TOKEN" \
                -H "xsrf-token: $XSRF_TOKEN" \
                -H "x-csrf-token: $XSRF_TOKEN" \
                -H "x-xsrf-token: $XSRF_TOKEN" \
                -H "Cookie: auth=1; auth-method=google; cg_uuid=$CG_UUID; brd_sess_id=$BRD_SESS_ID; oauth-refresh-token=$OAUTH_REFRESH_TOKEN; oauth-token=$OAUTH_TOKEN; xsrf-token=$XSRF_TOKEN" \
                --data-raw "{\"uuid\":\"$UUID\",\"platform\":\"linux\",\"_csrf\":\"$XSRF_TOKEN\"}"
              systemctl restart earnapp earnapp_upgrader
              earnapp status || true
          - path: /etc/systemd/system/earnapp-bootstrap.service
            permissions: '0644'
            content: |
              [Unit]
              Description=Install and link EarnApp node once
              After=network-online.target
              Wants=network-online.target

              [Service]
              Type=oneshot
              EnvironmentFile=/etc/earnapp-bootstrap.env
              ExecStart=/root/install_earnapp_fixed.sh
              TimeoutStartSec=0
              RemainAfterExit=yes

              [Install]
              WantedBy=multi-user.target
          - path: /etc/earnapp-bootstrap.env
            permissions: '0600'
            content: |
              OAUTH_REFRESH_TOKEN=__OAUTH_REFRESH_TOKEN__
              OAUTH_TOKEN=__OAUTH_TOKEN__
              XSRF_TOKEN=__XSRF_TOKEN__
              BRD_SESS_ID=__BRD_SESS_ID__
              CG_UUID=__CG_UUID__
        runcmd:
          - [ systemctl, daemon-reload ]
          - [ systemctl, enable, earnapp-bootstrap.service ]
          - [ systemctl, start, --no-block, earnapp-bootstrap.service ]
        """
    ).strip()
    replacements = {
        "__HOSTNAME__": identity.hostname,
        "__MACHINE_ID__": identity.machine_id,
        "__OAUTH_REFRESH_TOKEN__": "${OAUTH_REFRESH_TOKEN}",
        "__OAUTH_TOKEN__": "${OAUTH_TOKEN}",
        "__XSRF_TOKEN__": "${XSRF_TOKEN}",
        "__BRD_SESS_ID__": "${BRD_SESS_ID}",
        "__CG_UUID__": "${CG_UUID}",
    }
    for old, new in replacements.items():
        user_data = user_data.replace(old, new)
    return "\n".join(
        [
            "set -euo pipefail",
            "export DEBIAN_FRONTEND=noninteractive",
            "apt-get update -y",
            "apt-get install -y ca-certificates curl wget qemu-system-x86 qemu-utils cloud-image-utils",
            "mkdir -p /state",
            "cd /state",
            "if [ ! -f ubuntu-24.04-server-cloudimg-amd64.img ]; then",
            "  wget -qO ubuntu-24.04-server-cloudimg-amd64.img https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
            "fi",
            "if [ ! -f earnapp.qcow2 ]; then",
            "  qemu-img create -f qcow2 -F qcow2 -b ubuntu-24.04-server-cloudimg-amd64.img earnapp.qcow2 12G",
            "fi",
            "cat >user-data <<'CLOUD'",
            user_data,
            "CLOUD",
            "cat >meta-data <<'META'",
            f"instance-id: {identity.uuid}",
            f"local-hostname: {identity.hostname}",
            "META",
            "cloud-localds seed.iso user-data meta-data",
            "exec qemu-system-x86_64 \\",
            "  -machine q35,accel=kvm:tcg \\",
            "  -cpu qemu64 \\",
            "  -m 1024 \\",
            "  -smp 2 \\",
            f"  -uuid {identity.uuid} \\",
            f"  -smbios type=1,manufacturer=CashPilot,product={identity.product},version=Ubuntu-24.04,serial={identity.serial},uuid={identity.uuid} \\",
            "  -drive file=earnapp.qcow2,if=none,id=drive0,format=qcow2 \\",
            f"  -device virtio-blk-pci,drive=drive0,serial={identity.serial} \\",
            "  -drive file=seed.iso,if=virtio,format=raw,readonly=on \\",
            f"  -device virtio-net-pci,netdev=net0,mac={identity.mac} \\",
            "  -netdev user,id=net0 \\",
            "  -nographic",
        ]
    )


def deploy_container(client, *, slug: str, network_mode: str | None, labels: dict[str, str], deploy_credentials: dict[str, str]):
    identity = new_identity(slug)
    env = {
        "OAUTH_REFRESH_TOKEN": str(deploy_credentials.get("oauth_refresh_token") or ""),
        "OAUTH_TOKEN": str(deploy_credentials.get("oauth_token") or ""),
        "XSRF_TOKEN": str(deploy_credentials.get("xsrf_token") or ""),
        "BRD_SESS_ID": str(deploy_credentials.get("brd_sess_id") or ""),
        "CG_UUID": str(deploy_credentials.get("cg_uuid") or ""),
    }
    labels = {**labels, "cashpilot.host-runtime": "qemu_systemd", "cashpilot.vm.uuid": identity.uuid}
    return client.containers.run(
        image="ubuntu:24.04",
        name=f"cashpilot-{slug}",
        environment=env,
        command=["/bin/bash", "-lc", render_qemu_command(identity)],
        volumes={f"cashpilot-{slug}-qemu": {"bind": "/state", "mode": "rw"}},
        network_mode=network_mode,
        labels=labels,
        detach=True,
        restart_policy={"Name": "always"},
    )
