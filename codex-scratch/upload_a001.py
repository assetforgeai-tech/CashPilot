import paramiko
from pathlib import Path

v = dict(line.strip().split("=", 1) for line in open(r"D:\1. WORK_true\CashPilot\vps\vps-test-us.txt", encoding="utf-8") if "=" in line)
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(v["ip"], port=int(v["port"]), username=v["user"], password=v["pass"], timeout=20)
root = "/opt/cashpilot/earnapp-a001-mac"
remote = "/tmp/earnapp-a001-mac"
stdin, stdout, stderr = c.exec_command("sudo -S bash -lc " + repr(f"rm -rf {remote} {root}; install -d -m 0755 -o {v['user']} -g {v['user']} {remote}"), get_pty=True)
stdin.write(v["pass"] + "\n"); stdin.flush(); stdout.read(); stderr.read()
sftp = c.open_sftp()
for p in Path(".tmp-a001-mac").iterdir():
    if p.is_file(): sftp.put(str(p), f"{remote}/{p.name}")
sftp.close()
cmd = f"sudo -S bash -lc " + repr(f"mv {remote} {root}; docker build --no-cache --pull=false -t cashpilot/earnapp-mac-canary:asset-a00e60cdff78 {root}")
stdin, stdout, stderr = c.exec_command(cmd, get_pty=True); stdin.write(v["pass"] + "\n"); stdin.flush()
print(stdout.read().decode()); print(stderr.read().decode())
c.close()
