#!/usr/bin/env python3
"""Chaos + TTR measurement.
Usage:
  python scripts/measure_ttr.py --container resilientpay-api --runs 3
  python scripts/measure_ttr.py --container resilientpay-db --runs 3
TTR = T2 - T1  (T1: first failed health check, T2: first OK after that)
"""
import argparse, csv, subprocess, time, urllib.request

# "crash" = process ko andar se girana. Docker ise asli crash maanta hai,
# isliye restart policy kaam karti hai. (docker kill/stop = manual stop, restart nahi hota)
CRASH = {
    "api":   ["exec", "resilientpay-api", "python", "-c", "import os,signal; os.kill(1, signal.SIGTERM)"],
    "nginx": ["exec", "resilientpay-nginx", "nginx", "-s", "stop"],
    "db":    ["exec", "-u", "postgres", "resilientpay-db", "pg_ctl", "stop", "-m", "immediate"],
}

def inject(container, action):
    cmd = CRASH[container.split("-")[-1]] if action == "crash" else [action, container]
    subprocess.run(["docker", *cmd], check=False, capture_output=True)
def healthy(url):
    try:
        return urllib.request.urlopen(url, timeout=1).status == 200
    except Exception:
        return False

def wait_until(url, want, timeout=300, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        if healthy(url) == want:
            return time.time()
        time.sleep(step)
    raise TimeoutError(f"health never became {'OK' if want else 'FAILED'}")

def push_cw(name, value, scenario, region):
    import boto3
    boto3.client("cloudwatch", region_name=region).put_metric_data(
        Namespace="ResilientPay",
        MetricData=[{"MetricName": name, "Value": value, "Unit": "Seconds",
                     "Dimensions": [{"Name": "Scenario", "Value": scenario}]}])

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost/health")
    p.add_argument("--container", default="resilientpay-api")
    p.add_argument("--action", choices=["crash", "kill", "stop"], default="crash")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--label", default="restart_always", help="e.g. baseline / restart_always")
    p.add_argument("--cloudwatch", action="store_true")
    p.add_argument("--region", default="ap-south-1")
    a = p.parse_args()

    scenario = f"{a.container}:{a.action}:{a.label}"
    results = []
    for i in range(1, a.runs + 1):
        wait_until(a.url, True)
        time.sleep(2)
        print(f"[run {i}] injecting failure: {a.action} on {a.container}")
        inject(a.container, a.action)
        t1 = wait_until(a.url, False, timeout=30)
        try:
            t2 = wait_until(a.url, True, timeout=120)
            ttr = round(t2 - t1, 2)
        except TimeoutError:
            ttr = None
            print("  not recovered automatically. Starting manually.")
            subprocess.run(["docker", "start", a.container], capture_output=True)
        results.append(ttr)
        print(f"[run {i}] TTR = {ttr} s  {'PASS' if ttr is not None and ttr < 60 else 'FAIL'} (SLA < 60s)")
        if a.cloudwatch and ttr is not None:
            push_cw("TTR_seconds", ttr, scenario, a.region)
        time.sleep(5)

    ok = [r for r in results if r is not None]
    avg = round(sum(ok) / len(ok), 2) if ok else None
    print(f"\nScenario: {scenario}\nRuns: {results}\nAverage TTR: {avg} s")
    with open("docs/ttr-results.csv", "a", newline="") as f:
        csv.writer(f).writerow([scenario, *results, avg])

if __name__ == "__main__":
    main()