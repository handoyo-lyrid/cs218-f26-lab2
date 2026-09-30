#!/usr/bin/env python3
"""CS 218 Lab 2 driver: measures your container and your VM, and writes the file you submit.

Run it on your own laptop (not inside a container or the VM): it has to start and stop
both of them and time how long each takes to answer. Python 3.9 or newer, standard
library only.

You do not have to read this file to do the lab, but nothing in it is hidden from you.
It runs ordinary docker commands and the start and stop commands you give it, sends
plain HTTP requests to the workload, and records what came back. Every number in your
results file is something this script measured on your machine.
"""

import argparse
import base64
import hashlib
import http.client
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(ROOT, "results")
APP_PATH = os.path.join(ROOT, "app", "app.py")
SCHEMA_VERSION = 1

IMAGE = "cs218-lab2"
APP_CONTAINER = "lab2-app"
HOG_CONTAINER = "lab2-hog"
HOG_IMAGE = "alpine:3.20"
CONTAINER_URL = "http://127.0.0.1:8080"


# ------------------------------------------------------------------ small helpers


def banner(text):
    print()
    print("=" * 78)
    print(text)
    print("=" * 78)


def save(name, obj):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    obj = dict(obj, schema=SCHEMA_VERSION, recorded_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    with open(os.path.join(RESULTS_DIR, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1)
    print(f"\nWrote results/{name}")


def load(name):
    path = os.path.join(RESULTS_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def app_sha256():
    with open(APP_PATH, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def kill_tree(proc):
    # With shell=True the command runs under a shell, and killing only the shell can leave
    # the real program running with our output pipes still open.
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            proc.kill()


def run(args, timeout=300, check=True, shell=False):
    """Run a command, return (returncode, stdout, seconds). `args` is a list unless shell."""
    started = time.perf_counter()
    try:
        proc = subprocess.Popen(args, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=(os.name != "nt"))
    except FileNotFoundError:
        sys.exit(f"Could not run {args[0] if isinstance(args, list) else args!r}. Is it installed "
                 "and on your PATH?")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return None, "", time.perf_counter() - started
    elapsed = time.perf_counter() - started
    if check and proc.returncode != 0:
        cmd = args if shell else " ".join(args)
        sys.exit(f"This command failed:\n  {cmd}\n{(err or out).strip()}")
    return proc.returncode, out.strip(), elapsed


# No proxy lookup: on Windows the default opener reads the proxy settings on every call,
# which adds jitter to exactly the latencies this lab measures.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url, timeout=5):
    """GET a JSON endpoint. Returns (ok, body, milliseconds)."""
    started = time.perf_counter()
    try:
        with OPENER.open(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            ok = resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False, None, (time.perf_counter() - started) * 1000
    return ok, body, (time.perf_counter() - started) * 1000


def wait_until_up(base_url, timeout, interval=0.05):
    """Poll /health until it answers. Returns seconds waited, or None on timeout."""
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if get(base_url + "/health", timeout=1)[0]:
            return time.perf_counter() - started
        time.sleep(interval)
    return None


def wait_until_down(base_url, timeout):
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if not get(base_url + "/health", timeout=1)[0]:
            return True
        time.sleep(0.25)
    return False


def nearest_rank(sorted_values, p):
    """Percentile by nearest rank, the definition used in the Session 4 slides."""
    if not sorted_values:
        return None
    rank = math.ceil(p / 100 * len(sorted_values))
    return sorted_values[max(1, rank) - 1]


def summarize(samples):
    s = sorted(samples)
    return {
        "n": len(s),
        "p50_ms": round(nearest_rank(s, 50), 2),
        "p90_ms": round(nearest_rank(s, 90), 2),
        "p99_ms": round(nearest_rank(s, 99), 2),
        "max_ms": round(s[-1], 2),
        "mean_ms": round(statistics.fmean(s), 2),
    }


def median(values):
    return round(statistics.median(values), 3) if values else None


def host_info():
    info = {
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    rc, out, _ = run(["docker", "info", "--format",
                      "{{.ServerVersion}}|{{.OperatingSystem}}|{{.KernelVersion}}|{{.NCPU}}|{{.MemTotal}}"],
                     check=False)
    if rc == 0 and out.count("|") == 4:
        v, osname, kernel, ncpu, mem = out.split("|")
        info["docker"] = {"version": v, "os": osname, "kernel": kernel,
                          "cpus": int(ncpu), "mem_gib": round(int(mem) / 2**30, 2)}
    return info


def base_url(url):
    url = url.rstrip("/")
    if not url.startswith("http"):
        url = "http://" + url
    return url


def require_container_app():
    if not get(CONTAINER_URL + "/health")[0]:
        sys.exit("Your container is not answering on port 8080. Run `python lab.py container-start` "
                 "first; it leaves the container running for the later parts.")


def require_vm(url):
    ok, body, _ = get(url + "/probe")
    if not ok:
        sys.exit(f"Nothing answered at {url}/probe. Is your VM running, and is that its address? "
                 "See VM-SETUP.md for how to find it.")
    return body


# ------------------------------------------------------------------ render


def render():
    """Embed app/app.py into the cloud-init template, producing vm/cloud-init.yaml."""
    with open(os.path.join(ROOT, "vm", "cloud-init.template.yaml"), encoding="utf-8") as fh:
        template = fh.read()
    with open(APP_PATH, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    out = os.path.join(ROOT, "vm", "cloud-init.yaml")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(template.replace("{{APP_B64}}", encoded))
    print(f"Wrote vm/cloud-init.yaml with app.py embedded (sha256 {app_sha256()[:12]}...).")


def cloud_init_app_sha():
    path = os.path.join(ROOT, "vm", "cloud-init.yaml")
    if not os.path.exists(path):
        return None
    lines = open(path, encoding="utf-8").read().splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "path: /opt/lab2/app.py":
            for follow in lines[i:i + 5]:
                if follow.strip().startswith("content:"):
                    data = base64.b64decode(follow.split("content:", 1)[1].strip())
                    return hashlib.sha256(data).hexdigest()
    return None


# ------------------------------------------------------------------ Part 0: build


def dockerfile_facts(text):
    """Read the parts of the Dockerfile the requirements talk about. Deliberately simple."""
    lines, current = [], ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            current += stripped[:-1] + " "
            continue
        lines.append(current + stripped)
        current = ""
    facts = {"from": [], "user": None, "healthcheck": False, "expose": [], "cmd": None}
    for line in lines:
        word, _, rest = line.partition(" ")
        word = word.upper()
        if word == "FROM":
            facts["from"].append(rest.split()[0])
        elif word == "USER":
            facts["user"] = rest.strip()
        elif word == "HEALTHCHECK" and "NONE" not in rest.upper().split()[:1]:
            facts["healthcheck"] = True
        elif word == "EXPOSE":
            facts["expose"] += rest.split()
        elif word in ("CMD", "ENTRYPOINT"):
            facts["cmd"] = {"instruction": word, "exec_form": rest.strip().startswith("["), "text": rest.strip()}
    return facts


def build():
    banner("PART 0  Build your container image from your Dockerfile")
    path = os.path.join(ROOT, "Dockerfile")
    if not os.path.exists(path):
        sys.exit("There is no Dockerfile in this folder yet. Part 0 of the README says what it must do.")
    text = open(path, encoding="utf-8").read()
    print("Building (the first build downloads a base image, so give it a minute)...")
    _, _, seconds = run(["docker", "build", "-t", IMAGE, ROOT], timeout=900)
    _, out, _ = run(["docker", "image", "inspect", IMAGE, "--format", "{{json .}}"])
    inspect = json.loads(out)
    cfg = inspect.get("Config") or {}
    disk_size = run(["docker", "image", "ls", IMAGE, "--format", "{{.Size}}"], check=False)[1]
    facts = dockerfile_facts(text)
    final_from = facts["from"][-1] if facts["from"] else ""
    tag = final_from.split("@")[0].rsplit(":", 1)[1] if ":" in final_from.split("/")[-1] else None
    result = {
        "dockerfile": text,
        "facts": facts,
        "build_seconds": round(seconds, 2),
        "image_size_on_disk": disk_size.splitlines()[0] if disk_size else None,
        "image_content_size_mb": round(inspect.get("Size", 0) / 1e6, 1),
        "image_layers": len((inspect.get("RootFS") or {}).get("Layers") or []),
        "image_user": cfg.get("User") or "",
        "image_healthcheck": bool(cfg.get("Healthcheck")),
        "image_exposed": sorted((cfg.get("ExposedPorts") or {}).keys()),
        "base_image": final_from,
        "base_pinned": bool(tag) and tag != "latest" or "@sha256:" in final_from,
    }
    print(f"\n  built in {result['build_seconds']} s, image {result['image_size_on_disk']} on disk "
          f"({result['image_content_size_mb']} MB to download), "
          f"{result['image_layers']} layers, base {final_from}")
    print(f"  user: {result['image_user'] or '(root, nothing set)'}   "
          f"healthcheck: {'yes' if result['image_healthcheck'] else 'no'}   "
          f"exposed: {', '.join(result['image_exposed']) or 'nothing'}   "
          f"CMD form: {'exec' if facts['cmd'] and facts['cmd']['exec_form'] else 'shell or missing'}")
    save("build.json", result)
    print("Next: python lab.py container-start")


# ------------------------------------------------------------------ Part 1: startup


def docker_rm(name):
    run(["docker", "rm", "-f", name], check=False, timeout=60)


def container_start(runs):
    banner(f"PART 1a  Start your container {runs} times, timed to its first answer")
    if run(["docker", "image", "inspect", IMAGE], check=False)[0] != 0:
        sys.exit("No image yet. Run `python lab.py build` first.")
    docker_rm(APP_CONTAINER)
    samples = []
    for i in range(1, runs + 1):
        t0 = time.perf_counter()
        run(["docker", "run", "-d", "--name", APP_CONTAINER, "-p", "8080:8080",
             "--cpus", "1", "--memory", "1g", IMAGE])
        cmd_s = time.perf_counter() - t0
        waited = wait_until_up(CONTAINER_URL, timeout=60)
        if waited is None:
            logs = run(["docker", "logs", "--tail", "15", APP_CONTAINER], check=False)[1]
            sys.exit(f"Run {i}: the container never answered on port 8080. Its last log lines:\n{logs}")
        ready_s = time.perf_counter() - t0
        probe = get(CONTAINER_URL + "/probe")[1] or {}
        sample = {"run": i, "run_command_s": round(cmd_s, 3), "ready_s": round(ready_s, 3),
                  "process_age_at_ready_s": (probe.get("app") or {}).get("ready", {}).get("process_age_at_ready_s")}
        if i < runs:
            sample["stop_s"] = round(run(["docker", "stop", APP_CONTAINER], timeout=60)[2], 3)
            docker_rm(APP_CONTAINER)
        samples.append(sample)
        print(f"  run {i:2}: docker run returned {sample['run_command_s']:.3f} s, "
              f"first answer {sample['ready_s']:.3f} s"
              + (f", docker stop took {sample['stop_s']:.2f} s" if "stop_s" in sample else ""))
    health = run(["docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                  APP_CONTAINER], check=False)[1]
    result = {
        "runs": samples,
        "median_ready_s": median([s["ready_s"] for s in samples]),
        "median_run_command_s": median([s["run_command_s"] for s in samples]),
        "median_stop_s": median([s["stop_s"] for s in samples if "stop_s" in s]),
        "health_status_after_start": health or "none",
        "host": host_info(),
    }
    print(f"\n  median time to first answer: {result['median_ready_s']} s   "
          f"median docker stop: {result['median_stop_s']} s")
    save("startup-container.json", result)
    print("The last container is still running on port 8080; the later parts use it.")


def vm_start(url, start_cmd, stop_cmd, runs, hypervisor, ip_cmd):
    banner(f"PART 1b  Stop and start your VM {runs} times, timed to its first answer")
    def resolve():
        if not ip_cmd:
            return url
        rc, out, _ = run(ip_cmd, shell=True, timeout=120, check=False)
        return url.replace("{ip}", out.split()[0]) if rc == 0 and out.strip() else None

    samples = []
    target = resolve()
    for i in range(1, runs + 1):
        stop_rc, _, stop_s = run(stop_cmd, shell=True, timeout=300, check=False)
        if stop_rc != 0:
            print(f"  (the stop command exited {stop_rc}; carrying on, since a VM that was already "
                  "stopped can do that)")
        if target and not wait_until_down(target, 120):
            sys.exit("After the stop command, the VM was still answering two minutes later. "
                     "Check that --stop really stops this VM.")
        t0 = time.perf_counter()
        start_rc, start_out, _ = run(start_cmd, shell=True, timeout=900, check=False)
        cmd_s = time.perf_counter() - t0
        if start_rc != 0:
            sys.exit(f"The start command failed (exit {start_rc}):\n  {start_cmd}\n{start_out}")
        target = resolve()
        if not target:
            sys.exit(f"--ip-cmd printed no address after the VM started: {ip_cmd}")
        waited = wait_until_up(target, timeout=900, interval=0.1)
        if waited is None:
            sys.exit(f"Run {i}: the VM never answered at {target}/health within 15 minutes.")
        ready_s = time.perf_counter() - t0
        probe = get(target + "/probe")[1] or {}
        ready = (probe.get("app") or {}).get("ready") or {}
        sample = {
            "run": i, "stop_s": round(stop_s, 3), "start_command_s": round(cmd_s, 3),
            "ready_s": round(ready_s, 3),
            "guest_kernel_uptime_at_ready_s": ready.get("kernel_uptime_at_ready_s"),
            "process_age_at_ready_s": ready.get("process_age_at_ready_s"),
            "boot_id": (probe.get("kernel") or {}).get("boot_id"),
        }
        k = sample["guest_kernel_uptime_at_ready_s"]
        sample["before_guest_kernel_s"] = round(ready_s - k, 3) if k is not None else None
        samples.append(sample)
        print(f"  run {i}: stop {sample['stop_s']:.1f} s | start command returned {cmd_s:.1f} s | "
              f"first answer {ready_s:.1f} s | guest kernel had been up {k} s of that")
    result = {
        "hypervisor": hypervisor, "url": url, "start_command": start_cmd, "stop_command": stop_cmd,
        "runs": samples,
        "median_ready_s": median([s["ready_s"] for s in samples]),
        "distinct_boot_ids": len({s["boot_id"] for s in samples if s["boot_id"]}),
        "host": host_info(),
    }
    print(f"\n  median time to first answer: {result['median_ready_s']} s over {runs} boots "
          f"({result['distinct_boot_ids']} distinct kernel boots)")
    save("startup-vm.json", result)


# ------------------------------------------------------------------ Part 2: memory


def parse_docker_mem(text):
    """'92.51MiB / 1GiB' -> 92.51 (MiB)."""
    used = text.split("/")[0].strip()
    units = {"B": 1 / 2**20, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1e3 / 2**20,
             "MB": 1e6 / 2**20, "GB": 1e9 / 2**20}
    for unit in sorted(units, key=len, reverse=True):
        if used.endswith(unit):
            return round(float(used[: -len(unit)]) * units[unit], 1)
    return None


def kb(value):
    try:
        return int(str(value).split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def memory(vm_url, host_mb, host_source, vm_docker):
    banner("PART 2  Memory: what each one costs the host, against what the workload uses")
    require_container_app()
    c_probe = get(CONTAINER_URL + "/probe")[1]
    stats = run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", APP_CONTAINER])[1]
    current = c_probe["cgroup"].get("memory.current") or ""
    # The container's cost to the host is what the host kernel charges to its cgroup. The
    # container reads that same number from inside, because it is the same kernel.
    # `docker stats` shows it minus reclaimable file cache, so it can come out below the
    # workload's own RSS; it is recorded alongside for comparison.
    container = {
        "host_mb": round(int(current) / 2**20, 1) if current.isdigit() else parse_docker_mem(stats),
        "host_source": "cgroup memory.current (the host kernel's charge for this container)",
        "docker_stats_mb": parse_docker_mem(stats),
        "app_rss_mb": round(kb(c_probe["memory"]["self_VmRSS"]) / 1024, 1),
        "app_rss_anon_mb": round((kb(c_probe["memory"].get("self_RssAnon")) or 0) / 1024, 1),
        "app_rss_file_mb": round((kb(c_probe["memory"].get("self_RssFile")) or 0) / 1024, 1),
    }
    v_probe = require_vm(vm_url)
    vm_docker_stats = None
    if vm_docker:
        rss = run(["docker", "exec", vm_docker, "sh", "-c",
                   "grep VmRSS /proc/$(cat /run/qemu.pid)/status"], check=False)[1]
        vm_docker_stats = parse_docker_mem(
            run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", vm_docker])[1])
        if kb(rss.split(":", 1)[-1]) is not None:
            host_mb = kb(rss.split(":", 1)[-1]) / 1024
            host_source = f"VmRSS of the qemu-system-x86_64 process in {vm_docker}"
    if host_mb is None:
        sys.exit("Give the VM's host-side memory with --vm-host-mb and say where you read it with "
                 "--vm-host-source. VM-SETUP.md says where to look on your system.")
    m = v_probe["memory"]
    total, avail = m["MemTotal_kB"] / 1024, m["MemAvailable_kB"] / 1024
    app_rss = kb(m["self_VmRSS"]) / 1024
    vm = {
        "host_mb": round(host_mb, 1), "host_source": host_source or "(not given)",
        "docker_stats_mb": vm_docker_stats,
        "app_rss_mb": round(app_rss, 1),
        "app_rss_anon_mb": round((kb(m.get("self_RssAnon")) or 0) / 1024, 1),
        "app_rss_file_mb": round((kb(m.get("self_RssFile")) or 0) / 1024, 1),
        "guest_memtotal_mb": round(total, 1), "guest_memavailable_mb": round(avail, 1),
        "guest_used_mb": round(total - avail, 1),
        "guest_os_without_app_mb": round(total - avail - app_rss, 1),
        "guest_page_cache_mb": round((m.get("Cached_kB", 0) + m.get("Buffers_kB", 0)) / 1024, 1),
        "guest_kernel_slab_mb": round(m.get("Slab_kB", 0) / 1024, 1),
        "guest_uptime_s": v_probe["kernel"]["uptime_s"],
    }
    if vm["guest_uptime_s"] and vm["guest_uptime_s"] < 120:
        print("  Note: the VM booted less than two minutes ago. Boot-time activity inflates these "
              "numbers; consider waiting and running this again.")
    for label, d in (("container", container), ("VM", vm)):
        print(f"  {label:9}: host-side {d['host_mb']} MB | workload RSS {d['app_rss_mb']} MB "
              f"({d['app_rss_anon_mb']} private, {d['app_rss_file_mb']} file-backed) | "
              f"host-side minus RSS {round(d['host_mb'] - d['app_rss_mb'], 1)} MB")
    print(f"  inside the VM: {vm['guest_used_mb']} MB in use of {vm['guest_memtotal_mb']} MB, "
          f"of which the workload is {vm['app_rss_mb']} MB; the guest OS itself is "
          f"{vm['guest_os_without_app_mb']} MB ({vm['guest_page_cache_mb']} MB of it page cache)")
    save("memory.json", {"container": container, "vm": vm, "host": host_info()})


# ------------------------------------------------------------------ Part 3: isolation


PROBE_ROWS = [
    ("kernel release", ("kernel", "release")),
    ("kernel boot id", ("kernel", "boot_id")),
    ("kernel uptime (s)", ("kernel", "uptime_s")),
    ("operating system", ("os_release",)),
    ("python", ("app", "python")),
    ("app.py sha256", ("app", "source_sha256")),
    ("our PID", ("app", "pid")),
    ("PID 1 is", ("processes", "pid1_comm")),
    ("processes visible", ("processes", "visible")),
    ("MemTotal (kB)", ("memory", "MemTotal_kB")),
    ("cgroup memory.max", ("cgroup", "memory.max")),
    ("CPUs visible", ("cpu", "os_cpu_count")),
    ("cgroup cpu.max", ("cgroup", "cpu.max")),
    ("uid", ("identity", "uid")),
    ("uid_map", ("identity", "uid_map")),
    ("capabilities allowed", ("identity", "cap_bounding_count")),
    ("seccomp mode", ("identity", "seccomp_mode")),
    ("hardware vendor", ("virtualization", "dmi_sys_vendor")),
    ("CPU says hypervisor", ("virtualization", "cpu_hypervisor_flag")),
    ("user namespace", ("namespaces", "user")),
    ("time namespace", ("namespaces", "time")),
]


def dig(d, path):
    for key in path:
        d = (d or {}).get(key) if isinstance(d, dict) else None
    return d


def probe(vm_url):
    banner("PART 3a  The same questions, asked from inside each one")
    require_container_app()
    c = get(CONTAINER_URL + "/probe")[1]
    v = require_vm(vm_url)
    print(f"  {'':22} {'container':<30} {'VM':<30}")
    for label, path in PROBE_ROWS:
        cv, vv = str(dig(c, path)), str(dig(v, path))
        mark = " " if cv == vv else "*"
        print(f"{mark} {label:22} {cv[:30]:<30} {vv[:30]:<30}")
    print("\n  * marks the rows that differ.")
    same_app = c["app"]["source_sha256"] == v["app"]["source_sha256"] == app_sha256()
    if not same_app:
        print("  WARNING: the container and the VM are not running the same app.py as this folder. "
              "Rebuild the image, or re-render cloud-init and re-create the VM.")
    save("probe-container.json", c)
    save("probe-vm.json", v)


def crash(vm_url, crash_cmd):
    banner("PART 3b  Crash the VM's kernel, and watch who notices")
    if "lab2-panic" not in crash_cmd:
        sys.exit("The crash command must run lab2-panic inside the VM, exactly as VM-SETUP.md gives "
                 "it. This script will not run anything else as a crash command.")
    require_container_app()
    v = require_vm(vm_url)
    if not (v.get("virtualization") or {}).get("lab2_vm_marker"):
        sys.exit(f"{vm_url} does not look like the Lab 2 VM (no marker file). Refusing to crash it.")
    c = get(CONTAINER_URL + "/probe")[1]
    if v["kernel"]["boot_id"] == c["kernel"]["boot_id"]:
        sys.exit("The VM and the container report the same kernel. That URL is not a separate VM.")
    vm_boot_before, host_boot_before = v["kernel"]["boot_id"], c["kernel"]["boot_id"]
    c_pid_before = c["app"]["pid"]

    timeline = {"container": [], "vm": []}
    stop = threading.Event()
    t0 = time.perf_counter()

    def watch(name, url, interval):
        while not stop.is_set():
            ok, body, _ = get(url + "/health", timeout=1)
            timeline[name].append((round(time.perf_counter() - t0, 2), ok, (body or {}).get("boot_id")))
            time.sleep(interval)

    threads = [threading.Thread(target=watch, args=("container", CONTAINER_URL, 0.1), daemon=True),
               threading.Thread(target=watch, args=("vm", vm_url, 0.25), daemon=True)]
    for t in threads:
        t.start()
    time.sleep(2)
    print(f"  running: {crash_cmd}")
    # Fire and do not wait on it: the command's own connection into the VM dies with the
    # VM's kernel, and how long it takes to notice varies by hypervisor. The health checks
    # are what tell us what happened.
    crasher = subprocess.Popen(crash_cmd, shell=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=(os.name != "nt"))

    went_down = wait_until_down(vm_url, 60)
    down_at = time.perf_counter() - t0
    print("  VM stopped answering." if went_down else "  WARNING: the VM never stopped answering.")
    came_back, reminded = None, False
    while went_down and time.perf_counter() - t0 < 600:
        ok, body, _ = get(vm_url + "/health", timeout=1)
        if ok and body.get("boot_id") != vm_boot_before:
            came_back = time.perf_counter() - t0
            break
        if not reminded and time.perf_counter() - t0 > 120:
            print("  Still down after two minutes. If your hypervisor has not restarted it, start the "
                  "VM yourself now (for example `multipass start lab2`); this keeps waiting.")
            reminded = True
        time.sleep(0.5)
    time.sleep(2)
    stop.set()
    for t in threads:
        t.join(timeout=3)
    if crasher.poll() is None:
        kill_tree(crasher)

    c_after = get(CONTAINER_URL + "/probe")[1] or {}
    v_after = get(vm_url + "/probe")[1] or {}
    c_ok = sum(1 for _, ok, _ in timeline["container"] if ok)
    result = {
        "crash_command": crash_cmd,
        "vm_boot_id_before": vm_boot_before, "vm_boot_id_after": (v_after.get("kernel") or {}).get("boot_id"),
        "vm_went_down": went_down, "vm_down_at_s": round(down_at, 2),
        "vm_back_at_s": round(came_back, 2) if came_back else None,
        "vm_outage_s": round(came_back - down_at, 2) if came_back else None,
        "container_checks": len(timeline["container"]), "container_ok": c_ok,
        "container_same_process": (c_after.get("app") or {}).get("pid") == c_pid_before
        and (c_after.get("kernel") or {}).get("boot_id") == host_boot_before,
        "timeline": timeline,
    }
    print(f"\n  VM: down at {result['vm_down_at_s']} s, back at {result['vm_back_at_s']} s "
          f"(outage {result['vm_outage_s']} s), new kernel: "
          f"{result['vm_boot_id_after'] not in (None, vm_boot_before)}")
    print(f"  container: answered {c_ok} of {result['container_checks']} health checks during that "
          f"time, same process and same kernel afterwards: {result['container_same_process']}")
    save("crash.json", result)


# ------------------------------------------------------------------ Part 4: noisy neighbour


def hog_start(cpus_limit, ncpu):
    docker_rm(HOG_CONTAINER)
    args = ["docker", "run", "-d", "--rm", "--name", HOG_CONTAINER]
    if cpus_limit:
        args += ["--cpus", str(cpus_limit)]
    script = f"i=0; while [ $i -lt {ncpu} ]; do (while :; do :; done) & i=$((i+1)); done; wait"
    run(args + [HOG_IMAGE, "sh", "-c", script], timeout=300)


def measure_work(url, n, warmup=20):
    """n sequential /work requests over one reused connection, the way a service calls another."""
    host, port = url.split("//", 1)[1].rsplit(":", 1)
    conn = None
    client, server, failed = [], [], 0
    for i in range(n + warmup):
        started = time.perf_counter()
        try:
            conn = conn or http.client.HTTPConnection(host, int(port), timeout=10)
            conn.request("GET", "/work")
            body = json.loads(conn.getresponse().read())
        except (OSError, http.client.HTTPException, ValueError):
            failed += 1
            conn = None
            continue
        ms = (time.perf_counter() - started) * 1000
        if i >= warmup:
            client.append(ms)
            server.append(body["server_ms"])
    if conn:
        conn.close()
    if not client:
        sys.exit(f"No /work request to {url} succeeded.")
    return {"client": summarize(client), "server": summarize(server), "failed": failed}


def neighbour(vm_url, n):
    banner("PART 4  A noisy neighbour: the same requests, with a CPU hog next door")
    require_container_app()
    targets = {"container": CONTAINER_URL}
    if vm_url:
        require_vm(vm_url)
        targets["vm"] = vm_url
    ncpu = (host_info().get("docker") or {}).get("cpus") or os.cpu_count() or 4
    print(f"  The hog is one busy loop per CPU Docker can see: {ncpu} of them.")
    run(["docker", "pull", "-q", HOG_IMAGE], timeout=600)
    phases = [("baseline", None, "nobody else running"),
              ("hog", 0, f"{ncpu} busy loops, no limit"),
              ("hog_limited", 1, f"the same {ncpu} loops, limited to --cpus 1")]
    out = {name: {} for name in targets}
    for phase, limit, what in phases:
        print(f"\n  phase {phase}: {what}")
        if limit is not None:
            hog_start(limit, ncpu)
            time.sleep(2)
        try:
            for name, url in targets.items():
                r = measure_work(url, n)
                out[name][phase] = r
                print(f"    {name:9}: p50 {r['client']['p50_ms']:7.2f} ms   p99 {r['client']['p99_ms']:7.2f} ms"
                      f"   max {r['client']['max_ms']:7.2f} ms   (server-side p99 {r['server']['p99_ms']} ms)")
        finally:
            if limit is not None:
                docker_rm(HOG_CONTAINER)
    save("neighbour.json", {"hog_loops": ncpu, "requests_per_phase": n, "targets": out, "host": host_info()})


# ------------------------------------------------------------------ verify


def student_identity():
    path = os.path.join(ROOT, "student.txt")
    if not os.path.exists(path):
        return None
    lines = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
    return {"name": lines[0], "sjsu_id": lines[1]} if len(lines) >= 2 else None


def git_head():
    rc, out, _ = run(["git", "-C", ROOT, "rev-parse", "HEAD"], check=False, timeout=20)
    return out if rc == 0 else None


def fingerprint(docs):
    """Hash the raw timings so two submissions can be told apart. A duplicate check, nothing more."""
    h = hashlib.sha256()
    for name in sorted(docs):
        h.update(json.dumps(docs[name], sort_keys=True).encode())
    return h.hexdigest()[:16]


CHECKS = [
    ("build", "Part 0: the image builds from your Dockerfile"),
    ("dockerfile", "Part 0: the Dockerfile meets all six requirements"),
    ("container_start", "Part 1: ten container starts, all answered"),
    ("vm_start", "Part 1: three VM boots, all answered, hypervisor named"),
    ("memory_container", "Part 2: container memory recorded"),
    ("memory_vm", "Part 2: VM memory recorded, with where you read it"),
    ("probes", "Part 3: both probes, same app.py, two different kernels"),
    ("crash", "Part 3: the VM's kernel crashed and came back; the container never noticed"),
    ("neighbour_container", "Part 4: all three phases against the container"),
    ("neighbour_vm", "Part 4: all three phases against the VM"),
]


def verify():
    banner("VERIFY  What you have, and what is still missing")
    names = ["build.json", "startup-container.json", "startup-vm.json", "memory.json",
             "probe-container.json", "probe-vm.json", "crash.json", "neighbour.json"]
    docs = {n: load(n) for n in names}
    b, sc, sv, mem, pc, pv, cr, nb = (docs[n] for n in names)
    sha = app_sha256()
    reqs = {}
    if b:
        f = b["facts"]
        reqs = {
            "pinned base image": b["base_pinned"],
            "Python 3.12, as in the VM": bool(pc) and pc["app"]["python"].startswith("3.12."),
            "copies app/app.py unchanged": bool(pc) and pc["app"]["source_sha256"] == sha,
            "runs as a non-root user": bool(pc) and pc["identity"]["uid"] != 0,
            "has a HEALTHCHECK": b["image_healthcheck"],
            "exec-form CMD, so python is PID 1": bool(f["cmd"] and f["cmd"]["exec_form"])
            and bool(pc) and pc["app"]["pid"] == 1,
        }
    ok = {
        "build": bool(b),
        "dockerfile": bool(reqs) and all(reqs.values()),
        "container_start": bool(sc) and len(sc["runs"]) >= 10,
        "vm_start": bool(sv) and len(sv["runs"]) >= 3 and bool(sv["hypervisor"].strip()),
        "memory_container": bool(mem) and mem["container"]["host_mb"] is not None,
        "memory_vm": bool(mem) and mem["vm"]["host_mb"] is not None and mem["vm"]["host_source"] != "(not given)",
        "probes": bool(pc and pv) and pc["app"]["source_sha256"] == pv["app"]["source_sha256"] == sha
        and pc["kernel"]["boot_id"] != pv["kernel"]["boot_id"],
        "crash": bool(cr) and cr["vm_back_at_s"] is not None
        and cr["vm_boot_id_after"] not in (None, cr["vm_boot_id_before"])
        and cr["container_ok"] == cr["container_checks"] and cr["container_same_process"],
        "neighbour_container": bool(nb) and len(nb["targets"].get("container", {})) == 3,
        "neighbour_vm": bool(nb) and len(nb["targets"].get("vm", {})) == 3,
    }
    for key, label in CHECKS:
        print(f"  [{'x' if ok[key] else ' '}] {label}")
    if reqs and not all(reqs.values()):
        print("\n  Dockerfile requirements still missing: "
              + "; ".join(k for k, v in reqs.items() if not v))
    identity = student_identity()
    if not identity:
        print("\n  student.txt is missing or incomplete: your name on line 1, SJSU ID on line 2.")
    if cloud_init_app_sha() not in (None, sha):
        print("\n  vm/cloud-init.yaml carries a different app.py from app/app.py. Run `python lab.py render`.")
    passed = sum(ok.values())
    print(f"\n  {passed} of {len(CHECKS)} checks pass.")
    out = {
        "student": identity, "git_commit": git_head(), "app_sha256": sha,
        "fingerprint": fingerprint({k: v for k, v in docs.items() if v}),
        "checks": ok, "dockerfile_requirements": reqs, "results": docs, "host": host_info(),
    }
    save("lab2-results.json", out)
    print("Submit results/lab2-results.json and your report on Canvas.")


# ------------------------------------------------------------------ main


def main():
    p = argparse.ArgumentParser(description="CS 218 Lab 2 driver. See README.md for the order to run these in.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("render", help="embed app/app.py into vm/cloud-init.yaml")
    sub.add_parser("build", help="Part 0: build and check your Dockerfile")
    s = sub.add_parser("container-start", help="Part 1a: time container starts")
    s.add_argument("--runs", type=int, default=10)
    s = sub.add_parser("vm-start", help="Part 1b: time VM boots")
    s.add_argument("--url", required=True, help="the VM's app, e.g. http://192.168.64.5:8080")
    s.add_argument("--start", required=True, help="the command that starts your VM")
    s.add_argument("--stop", required=True, help="the command that stops your VM")
    s.add_argument("--hypervisor", required=True, help='what runs it, e.g. "Multipass 1.16 on macOS (QEMU+HVF)"')
    s.add_argument("--runs", type=int, default=3)
    s.add_argument("--ip-cmd", help="a command that prints the VM's IP after it starts (use {ip} in --url)")
    s = sub.add_parser("memory", help="Part 2: record memory for both")
    s.add_argument("--vm-url", required=True)
    s.add_argument("--vm-host-mb", type=float, help="the VM's memory as your host sees it, in MB")
    s.add_argument("--vm-host-source", help='where you read it, e.g. "Activity Monitor, qemu-system-aarch64"')
    s.add_argument("--vm-docker", help="if your VM runs in a Docker container (the QEMU route), its name")
    s = sub.add_parser("probe", help="Part 3a: probe both side by side")
    s.add_argument("--vm-url", required=True)
    s = sub.add_parser("crash", help="Part 3b: crash the VM's kernel and watch")
    s.add_argument("--vm-url", required=True)
    s.add_argument("--crash", required=True, help="the command from VM-SETUP.md that runs lab2-panic in your VM")
    s = sub.add_parser("neighbour", help="Part 4: latency with a CPU hog next door")
    s.add_argument("--vm-url")
    s.add_argument("--n", type=int, default=400)
    sub.add_parser("verify", help="check everything and write results/lab2-results.json")
    a = p.parse_args()

    if a.cmd == "render":
        render()
    elif a.cmd == "build":
        build()
    elif a.cmd == "container-start":
        container_start(a.runs)
    elif a.cmd == "vm-start":
        vm_start(base_url(a.url), a.start, a.stop, a.runs, a.hypervisor, a.ip_cmd)
    elif a.cmd == "memory":
        memory(base_url(a.vm_url), a.vm_host_mb, a.vm_host_source, a.vm_docker)
    elif a.cmd == "probe":
        probe(base_url(a.vm_url))
    elif a.cmd == "crash":
        crash(base_url(a.vm_url), a.crash)
    elif a.cmd == "neighbour":
        neighbour(base_url(a.vm_url) if a.vm_url else None, a.n)
    elif a.cmd == "verify":
        verify()


if __name__ == "__main__":
    main()
