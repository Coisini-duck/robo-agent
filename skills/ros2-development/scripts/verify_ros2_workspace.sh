#!/usr/bin/env bash
# Build a ROS 2 workspace and verify it WITHOUT leaving anything running.
#
#   verify_ros2_workspace.sh <dir-containing-packages> [pkg ...]
#
# If no package names are given, every directory in <dir> is treated as a package.
# Environment: ROS2_DISTRO (default jazzy), ROS2_WS (default $HOME/ros2_ws)
#
# Deliberately NOT using `set -u`: /opt/ros/*/setup.bash references unset vars.
set -o pipefail
SRC="${1:?usage: verify_ros2_workspace.sh <dir-containing-packages> [pkg ...]}"; shift || true
PKGS=("$@")
WS="${ROS2_WS:-$HOME/ros2_ws}"
DISTRO="${ROS2_DISTRO:-jazzy}"

[ -f "/opt/ros/$DISTRO/setup.bash" ] || { echo "!! /opt/ros/$DISTRO not found"; exit 1; }
. "/opt/ros/$DISTRO/setup.bash"

echo "################ A. environment ################"
echo "  ROS_DISTRO=${ROS_DISTRO:-<unset>}   WS=$WS"
echo "  DISPLAY=[${DISPLAY:-}]   WSLg=$([ -d /mnt/wslg ] && echo YES || echo NO)"

echo; echo "################ B. stage packages ################"
mkdir -p "$WS/src"
cp -r "$SRC"/* "$WS/src/"
ls "$WS/src"

echo; echo "################ C. colcon build ################"
( cd "$WS" && colcon build ) ; echo ">>> colcon exit = $?"
echo "    (accept only: per-package 'Finished <<<' + 'Summary: N packages finished' + exit 0)"

echo; echo "################ D. registration ################"
. "$WS/install/setup.bash"
if [ "${#PKGS[@]}" -eq 0 ]; then
  mapfile -t PKGS < <(ls "$WS/src")
fi
for p in "${PKGS[@]}"; do
  prefix=$(ros2 pkg prefix "$p" 2>&1)
  execs=$(ros2 pkg executables "$p" 2>&1 | tr '\n' ' ')
  echo "  $p"
  echo "      prefix: $prefix"
  echo "      execs : $execs"
  [ -d "$WS/install/$p/share/$p/launch" ] && \
      echo "      launch: $(ls "$WS/install/$p/share/$p/launch" | tr '\n' ' ')"
done

echo; echo "################ E. how to actually RUN one (bounded) ################"
cat <<'EOT'
  # Bound the launch so nothing survives the test:
  timeout -k 5 30 ros2 launch <pkg> <file>.launch.py > /tmp/run.log 2>&1 &
  sleep 8
  ros2 node list
  ros2 topic list
  ros2 topic hz <topic>          # configured rate != measured rate
  ros2 topic echo <topic> --once
  wait; tail -40 /tmp/run.log    # READ THE LOG - linters do not catch logic bugs

  # Headless-only packages (publishers/monitors) are the best first smoke test.
  # GUI packages need /mnt/wslg + DISPLAY to be set.
EOT

echo; echo "################ F. cleanup (exact PIDs, never name-match) ################"
PIDS=$(ps -eo pid=,args= \
  | grep -E "turtlesim_node|ros2 launch|/install/.*/lib/" \
  | grep -v grep | awk '{print $1}')
echo "  targets: ${PIDS:-（none）}"
for p in $PIDS; do
  echo "    kill $p  <- $(ps -p "$p" -o args= 2>/dev/null | cut -c1-68)"
  kill "$p" 2>/dev/null
done
sleep 2
echo "  remaining: $(ps -eo args= | grep -E 'turtlesim_node|ros2 launch|/install/.*/lib/' | grep -vc grep)"
echo
echo "################ VERIFY_DONE ################"
