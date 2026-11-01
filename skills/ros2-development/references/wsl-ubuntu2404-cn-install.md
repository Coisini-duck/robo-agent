# Installing ROS 2 Jazzy on WSL Ubuntu 24.04 from a China network

Verified end-to-end **2026-10-12**. Host: WSL2 distro `Ubuntu-24.04`, user
`root` (no sudo password needed — check with `sudo -n true`).

## Verified environment after install

| Item | Value |
|---|---|
| Distro | Ubuntu `24.04`, `VERSION_CODENAME=noble`, `UBUNTU_CODENAME=noble`, `amd64` |
| ROS | **ROS 2 Jazzy** |
| Apt source | `https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu noble main` |
| Package resolved | `ros-jazzy-desktop 0.11.0-1noble.20261006.040109` |
| Graphics | `DISPLAY=:0`, `/mnt/wslg` present → **WSLg works** (turtlesim window opened) |
| RMW | default (`rmw_fastrtps_cpp`) |
| Disk cost | ~4 GB (partition went 31 G → 35 G used) |

`ros2 --version` is **not a valid flag** on Jazzy — it prints argparse usage.
Confirm with `printenv ROS_DISTRO` or `ls /opt/ros/`.

## Reachability measurements (why the official commands fail here)

| URL / protocol | Result |
|---|---|
| `https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu/` | **200** |
| `https://keyserver.ubuntu.com/` (web) | **200** |
| gpg `--keyserver keyserver.ubuntu.com` (HKP, port **11371**) | **FAILS** — `Server indicated a failure` |
| `https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x<fpr>` (HTTPS 443) | **200**, 3,329 B, `-----BEGIN PGP PUBLIC KEY BLOCK-----` |
| `https://packages.ros.org/ros.key` | **http=000**, 0 bytes (unreachable) |
| `https://raw.githubusercontent.com/ros/rosdistro/master/ros.key` | times out (the official docs' method) |

**Lesson: a keyserver's web page returning 200 is not evidence that its HKP
port is open.** Probe the protocol you actually need.

Note the pks endpoint returned 3,329 B when fetched cleanly but 86,163 B on an
earlier probe — the response size varies, so validate the *content* (armored
header + fingerprint) rather than the size.

## Pitfall 1 — HKP blocked

```
gpg: keybox '/usr/share/keyrings/ros-archive-keyring.gpg' created
gpg: keyserver receive failed: Server indicated a failure
```

Fix — fetch over HTTPS and dearmor:

```bash
K=C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654
curl -fsSL --max-time 90 \
  "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x$K" -o /tmp/ros.key.asc
sudo gpg --dearmor < /tmp/ros.key.asc > /usr/share/keyrings/ros-archive-keyring.gpg
```

## Pitfall 2 — the key IS in the keyring, apt still says NO_PUBKEY

```
Get:2 https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu noble InRelease [4679 B]
Err:2 https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu noble InRelease
  The following signatures couldn't be verified because the public key is
  not available: NO_PUBKEY F42ED6FBAB17C654
E: The repository '... noble InRelease' is not signed.
```

Meanwhile the keyring clearly held it:

```
$ gpg --no-default-keyring --keyring .../ros-archive-keyring.gpg --list-keys --with-colons
pub:-:4096:1:F42ED6FBAB17C654:1559176854:1906547974::-:::scSC::::::23::0:
fpr:::::::::C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654:
$ ls -l /usr/share/keyrings/ros-archive-keyring.gpg
-rw------- 1 root root 2365 ...          <-- 600, root-only
```

**Root cause:** `gpg --dearmor` creates the output with mode `600`. apt performs
signature verification **dropping privileges to the `_apt` user**, which cannot
read a 600 root-owned file — so from apt's point of view the key is absent. The
error message points at the key, not at the file, which is what makes this
expensive.

**Fix, one line:**

```bash
sudo chmod 0644 /usr/share/keyrings/ros-archive-keyring.gpg
```

Immediately after: `apt-get update` fetches `noble/main amd64 Packages [2112 kB]`
and `apt-cache policy ros-jazzy-desktop` prints
`Candidate: 0.11.0-1noble.20261006.040109`.

**Do not** paper over this with `[trusted=yes]` on the repo line. That disables
the verification the whole exercise depends on, and hides a real misconfiguration.

## Generic form of the lesson

When apt reports a missing key, check **both** facts separately:

1. Is the key actually in the keyring? (`gpg --list-keys` / grep the fingerprint)
2. Can the user apt verifies as **read the file**? (`ls -l` — expect `644`,
   readable; `gpg --dearmor` gives you `600`)

If (1) is true and apt still complains, the answer is (2), not the key.
