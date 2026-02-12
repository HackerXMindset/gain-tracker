import json
import os
import requests


def _get_api_key() -> str:
    key = os.environ.get("SVS_API_KEY", "").strip()
    if key:
        return key
    return input("SVS API key: ").strip()


def _get_mints() -> list[str]:
    raw = input("CA (comma or space separated): ").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace(",", " ").split()]
    return [p for p in parts if p]


def main() -> None:
    api_key = _get_api_key()
    mints = _get_mints()
    if not api_key:
        print("ERROR: Missing API key")
        return
    if not mints:
        print("ERROR: No mint addresses provided")
        return

    payload = {"mints": mints[:36]}
    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key,
    }

    try:
        response = requests.post(
            "https://free.api.solanavibestation.com/metadata",
            headers=headers,
            data=json.dumps(payload),
            timeout=15,
        )
        print(response.status_code)
        text = response.text
        try:
            print(json.dumps(response.json(), indent=2))
        except Exception:
            print(text)
    except Exception as exc:
        print("ERROR:", exc)


if __name__ == "__main__":
    main()
