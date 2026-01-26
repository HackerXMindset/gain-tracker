import urllib.request

addr = input("Token contract address: ").strip()
url = (
    "https://web3.okx.com/priapi/v1/dx/market/v2/token/overview"
    f"?chainId=501&tokenContractAddress={addr}"
)

try:
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = resp.read()
        print(raw.decode("utf-8", errors="replace"))
except Exception as exc:
    print("ERROR:", exc)
