from pathlib import Path

import paramiko

KEY = Path(r"D:\1. WORK_true\CashPilot\secret\ssh\azure-live-test-rsa")
TOKEN = Path(r"D:\AI_System\ghcr\info.txt").read_text().strip()
assets = {
    "macos": ("fd2fbbe2ff45", "fd2fbbe2ff45208e5b37ee6a93721b49f9cd1d4ef4528271b73adeac17206339"),
    "ios": ("8b064c518305", "8b064c518305ea38b8ab0ac51234f0bfa515597c3867fbd9be2dbe7a4eea2622"),
    "ubuntu": ("2da8b1802755", "2da8b18027555304152476b678b65a55bffdd4dac67ff95b46933b7fea602b4b"),
}
lines = [
    "set -euo pipefail",
    "read -r token",
    "printf '%s' \"$token\" | sudo docker login ghcr.io -u assetforgeai-tech --password-stdin >/dev/null",
]
for platform, (short, digest) in assets.items():
    local = f"cashpilot/earnapp-{'mac-canary' if platform == 'macos' else platform}:asset-{short}"
    remote = f"ghcr.io/assetforgeai-tech/cashpilot-earnapp-{platform}:asset-{short}"
    lines += [
        f"remote={remote!r}",
        f"local={local!r}",
        'sudo docker pull "$remote" >/dev/null',
        'sudo docker tag "$remote" "$local"',
        f"test \"$(sudo docker image inspect \"$local\" --format '{{{{index .RepoDigests 0}}}}' | grep -F '{digest}')\"",
        'echo "$local preloaded"',
    ]
lines += ["sudo docker logout ghcr.io >/dev/null"]
script = "\n".join(lines) + "\n"
for host in ("20.187.79.110", "20.210.93.220"):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username="kalinh", key_filename=str(KEY), timeout=30)
    stdin, stdout, stderr = client.exec_command("bash -s", timeout=1800)
    stdin.write(script + TOKEN + "\n")
    stdin.channel.shutdown_write()
    out, err = stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    client.close()
    print(f"=== {host} rc={rc} ===\n{out}{err}")
    if rc:
        raise SystemExit(rc)
