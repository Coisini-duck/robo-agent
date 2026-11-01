#!/usr/bin/env bash
# Install ROS 2 Jazzy on Ubuntu 24.04 (noble) from a China network.
# Verified 2026-10-12 on WSL2 Ubuntu-24.04 (running as root). Re-runnable.
#
# Both non-obvious fixes are baked in:
#   1. HKP port 11371 is blocked  -> fetch the key over HTTPS(443) instead
#   2. gpg --dearmor writes 600   -> apt verifies as _apt and cannot read it
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
LOG(){ echo; echo "########## $* ##########"; }

LOG "0. distro check (never guess the codename)"
grep -E '^(NAME|VERSION_ID|VERSION_CODENAME|UBUNTU_CODENAME)=' /etc/os-release || true
ARCH=$(dpkg --print-architecture); echo "arch=$ARCH"
. /etc/os-release
CODENAME="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
echo "detected codename = [$CODENAME]"
if [ "$CODENAME" != "noble" ]; then
  echo "!! expected noble (Ubuntu 24.04), got [$CODENAME] -- aborting rather than guessing"; exit 1
fi

LOG "1. base dependencies"
apt-get update -q
apt-get install -y -q curl gnupg lsb-release ca-certificates

LOG "2. ROS signing key over HTTPS (HKP 11371 is blocked on this network)"
K=C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654
curl -fsSL --max-time 90 \
  "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x$K" \
  -o /tmp/ros.key.asc
head -1 /tmp/ros.key.asc
echo "  downloaded $(wc -c < /tmp/ros.key.asc) bytes"
gpg --dearmor < /tmp/ros.key.asc > /usr/share/keyrings/ros-archive-keyring.gpg
# CRITICAL: dearmor produces -rw------- root-only; apt verifies as _apt
# user and cannot read it, which surfaces as a misleading NO_PUBKEY.
chmod 0644 /usr/share/keyrings/ros-archive-keyring.gpg
gpg --no-default-keyring --keyring /usr/share/keyrings/ros-archive-keyring.gpg \
    --list-keys --with-fingerprint --with-colons 2>/dev/null | grep -E '^(pub|fpr)' | head -4
ls -l /usr/share/keyrings/ros-archive-keyring.gpg

LOG "3. ROS 2 apt source (Tsinghua mirror)"
echo "deb [arch=$ARCH signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu $CODENAME main" \
  > /etc/apt/sources.list.d/ros2.list
cat /etc/apt/sources.list.d/ros2.list
apt-get update -q
echo "--- must show a Candidate: line, otherwise the key is still not being read ---"
apt-cache policy ros-jazzy-desktop | head -4

LOG "4. ros-jazzy-desktop (the large download)"
apt-get install -y -q ros-jazzy-desktop

LOG "5. dev tools and commonly needed packages"
apt-get install -y -q ros-dev-tools python3-colcon-common-extensions \
    ros-jazzy-turtlesim ros-jazzy-xacro ros-jazzy-urdfdom

LOG "6. verify"
set +u                                 # ROS setup.bash trips over set -u
. /opt/ros/jazzy/setup.bash
echo "ROS_DISTRO=${ROS_DISTRO:-<unset>}"
ls /opt/ros/
echo "turtlesim prefix: $(ros2 pkg prefix turtlesim 2>&1)"
echo "colcon:           $(command -v colcon || echo MISSING)"

LOG "7. auto-source in interactive shells"
for RC in /root/.bashrc /home/*/.bashrc; do
  [ -f "$RC" ] || continue
  if grep -q "opt/ros/jazzy/setup.bash" "$RC"; then
    echo "already present, skipping $RC"
  else
    printf '\nsource /opt/ros/jazzy/setup.bash\n' >> "$RC"; echo "wrote $RC"
  fi
done

echo; echo "ROS2_JAZZY_INSTALL_OK"
df -h / | tail -1
