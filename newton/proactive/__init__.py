"""Newton proactive engine — block 4.

The engine that turns Newton from "answers when asked" into "speaks up
usefully": background monitoring, pattern recognition, anticipation, and
mode-aware notifications.

Step 4.1 ships the monitoring foundation:

    * a long-running ``ProactiveDaemon`` that samples system state into
      ``system_metrics`` at an adaptive interval (5 s active, 60 s idle);
    * a pluggable ``Monitor`` ABC so the daemon doesn't hardcode the list
      of metrics it knows about;
    * a PID-file based start / stop / status surface, exposed through the
      ``newton proactive`` CLI subgroup.

Later steps (4.2 onwards) add threshold alerts, pattern learning, the
anticipation engine, and the delivery channels.
"""

from newton.proactive.daemon import ProactiveDaemon
from newton.proactive.monitors import Monitor, default_monitors

__all__ = ["Monitor", "ProactiveDaemon", "default_monitors"]
