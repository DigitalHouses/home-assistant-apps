"""Conservative product CI selection for the monorepo."""
import json
import os
import subprocess

PRODUCT_JOBS = {
    "digitalhouses_aqara_switch_app": "aqara-switch-app",
    "digitalhouses_zigbee_monitor_app": "zigbee-monitor-app",
    "digitalhouses_speedtest_app": "speedtest-app",
    "digitalhouses_network_app": "network-app",
    "digitalhouses_internet_app": "internet-app",
    "digitalhouses_presence_app": "presence-app",
    "digitalhouses_recorder_app": "recorder-app",
    "digitalhouses_backblaze_app": "backblaze-app",
    "digitalhouses_plex_agent": "plex-agent",
    "digitalhouses_pbs_agent": "pbs-agent",
    "digitalhouses_pve_agent": "pve-agent",
    "digitalhouses_sync_app": "sync-app",
    "digitalhouses_system_globals_app": "system-globals-app",
    "digitalhouses-stats": "stats-server",
}
ALL_JOBS = frozenset(PRODUCT_JOBS.values())
SHARED_PATHS = {
    "digitalhouses-stats/digitalhouses_stats/product_registry.json",
}


def select_jobs(paths):
    """Unknown/shared paths or empty diffs must run every job."""
    paths = list(paths)
    if not paths:
        return ALL_JOBS
    selected = set()
    for path in paths:
        root, sep, _ = path.partition("/")
        if not sep or root not in PRODUCT_JOBS or path in SHARED_PATHS:
            return ALL_JOBS
        selected.add(PRODUCT_JOBS[root])
    # Keep consumer checks for changes to product contracts.
    if selected - {"stats-server"}:
        selected.update(("sync-app", "stats-server"))
    # Electrica and System Globals share the day/night protocol.
    if selected.intersection(("aqara-switch-app", "system-globals-app")):
        selected.update(("aqara-switch-app", "system-globals-app"))
    return frozenset(selected)


def changed_paths(base, head):
    subprocess.run(["git", "merge-base", "--is-ancestor", base, head], check=True)
    data = subprocess.check_output(
        ["git", "diff", "--no-renames", "--name-only", "-z", base, head, "--"]
    )
    return [os.fsdecode(path) for path in data.split(b"\0") if path]


def main():
    try:
        paths = changed_paths(os.environ["BASE_SHA"], os.environ["HEAD_SHA"])
        jobs = select_jobs(paths)
    except (KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Cannot establish exact diff; full validation: {exc}")
        jobs = ALL_JOBS
    encoded = json.dumps(sorted(jobs), separators=(",", ":"))
    print(f"Selected CI jobs: {encoded}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write(f"jobs={encoded}\n")


if __name__ == "__main__":
    main()
