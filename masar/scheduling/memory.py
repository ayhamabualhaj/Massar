"""Stop a CP-SAT search when the process reaches its memory budget."""
import threading
from pathlib import Path

from ortools.sat.python import cp_model

DEFAULT_MEMORY_MB = 16384


def memory_mb():
    """Current Linux process RSS, including the native solver allocation."""
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) / 1024
    except (OSError, ValueError):
        pass
    return 0


def solve_with_memory_limit(solver, model, memory_limit_mb):
    """Stop search when observed process memory reaches the configured budget.

    This is a sampled guard, not an operating-system hard allocation limit.
    Keep a single worker to reduce native solver replication in the first place.
    """
    done = threading.Event()
    exceeded = threading.Event()
    peak = [memory_mb()]

    def monitor():
        """Sample memory usage while the solver runs and stop it if it reaches the limit."""
        while not done.is_set():
            peak[0] = max(peak[0], memory_mb())
            if peak[0] >= memory_limit_mb:
                exceeded.set()
                solver.stop_search()
            done.wait(0.1)

    if peak[0] >= memory_limit_mb:
        return cp_model.UNKNOWN, True, peak[0]
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        status = solver.solve(model)
    finally:
        done.set()
        watcher.join()
    return status, exceeded.is_set(), peak[0]
