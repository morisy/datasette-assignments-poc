"""Check every website in cities.csv responds (2xx/3xx). Exit 1 listing failures."""
import csv, os, sys, urllib.request

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "cities.csv")

def check(url):
    req = urllib.request.Request(url, method="HEAD",
        headers={"User-Agent": "Mozilla/5.0 (datasette-assignments URL check)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except Exception as e:
        # Some city sites reject HEAD; retry with GET before failing.
        try:
            req = urllib.request.Request(url,
                headers={"User-Agent": "Mozilla/5.0 (datasette-assignments URL check)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status
        except Exception as e2:
            return f"ERROR: {e2}"

def main():
    failures = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            status = check(row["website"])
            ok = isinstance(status, int) and status < 400
            print(f"{'ok ' if ok else 'FAIL'} {row['city']:20} {row['website']} -> {status}")
            if not ok:
                failures.append(row)
    if failures:
        print(f"\n{len(failures)} URL(s) need fixing:")
        for row in failures:
            print(f"  {row['city']}, {row['state']}: {row['website']}")
        sys.exit(1)
    print("\nAll 50 URLs OK")

if __name__ == "__main__":
    main()
