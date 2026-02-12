import urllib.request

addr = input("Token contract address: ").strip()
network = "solana"
url = f"https://api.dexpaprika.com/networks/{network}/tokens/{addr}"

try:
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = resp.read()
        print(raw.decode("utf-8", errors="replace"))
except Exception as exc:
    print("ERROR:", exc)
