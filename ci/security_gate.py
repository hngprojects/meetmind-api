import argparse
import json
from datetime import UTC, datetime


def load_json(path):
    with open(path) as f:
        return json.load(f)


def main(input_file, exceptions_file):
    findings = load_json(input_file)
    exceptions = {e["id"]: e for e in load_json(exceptions_file)}

    blocked = []

    for vuln in findings.get("vulnerabilities", []):
        vuln_id = vuln.get("id")

        severity = vuln.get("severity", "").lower()

        # Only care about high/critical
        if severity not in ["high", "critical"]:
            continue

        # Check exception
        if vuln_id in exceptions:
            exp = exceptions[vuln_id]

            # optional expiry check
            if exp.get("expires_at"):
                expires = datetime.fromisoformat(exp["expires_at"])
                if expires < datetime.now(UTC):
                    blocked.append((vuln_id, "EXPIRED EXCEPTION"))
                continue
            else:
                continue  # valid exception → ignore

        blocked.append((vuln_id, "NO EXCEPTION"))

    if blocked:
        print("\n❌ BLOCKED VULNERABILITIES:\n")
        for b in blocked:
            print(f"- {b[0]} ({b[1]})")
        return 1

    print("✅ No blocking vulnerabilities")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--exceptions", required=True)
    args = parser.parse_args()

    exit(main(args.input, args.exceptions))
