"""
One-time setup: authenticate happyautoec@outlook.com via Device Code Flow,
save the token cache to scripts/.outlook_token_cache.json for reuse.

Uses Microsoft Graph API to read mail (no IMAP needed).

Run once:
    .venv\\Scripts\\python.exe scripts\\debug\\setup_outlook_oauth.py
"""
import json
import os
import sys

import msal
import requests

CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"  # Thunderbird - supports MSA
SCOPES = ["https://graph.microsoft.com/Mail.Read"]
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", ".outlook_token_cache.json")
TOKEN_FILE = os.path.normpath(TOKEN_FILE)
USER = "happyautoec@outlook.com"


def get_token() -> str:
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_FILE):
        cache.deserialize(open(TOKEN_FILE).read())

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority="https://login.microsoftonline.com/consumers",
        token_cache=cache,
    )

    # Try silent refresh first
    accounts = app.get_accounts()
    result = None
    if accounts:
        print(f"Found cached account: {accounts[0]['username']}, trying silent refresh...")
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        print("No cached token, starting Device Code Flow...")
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "error" in flow:
            raise RuntimeError(f"Device flow error: {flow}")
        print("\n" + flow["message"] + "\n")
        result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        raise RuntimeError(f"Token error: {result['error']}: {result.get('error_description')}")

    # Save updated cache
    open(TOKEN_FILE, "w").write(cache.serialize())
    print(f"Token saved to {TOKEN_FILE}")
    return result["access_token"]


def test_graph(access_token: str):
    print(f"\nTesting Graph API as {USER}...")
    headers = {"Authorization": f"Bearer {access_token}"}

    # Get top 5 messages
    r = requests.get(
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
        "?$select=id,subject,from,receivedDateTime&$top=5&$orderby=receivedDateTime desc",
        headers=headers,
    )
    r.raise_for_status()
    messages = r.json().get("value", [])
    print(f"Inbox has messages. Latest {len(messages)}:")
    for m in messages:
        print(f"  [{m['receivedDateTime']}] {m['subject'][:60]} — from {m['from']['emailAddress']['address']}")
    print("\nGraph API test PASSED!")


if __name__ == "__main__":
    token = get_token()
    test_graph(token)
