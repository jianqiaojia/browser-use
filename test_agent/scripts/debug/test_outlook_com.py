"""Diagnostic script to inspect Outlook COM accounts and stores."""
import win32com.client


def main():
    print("Connecting to Outlook COM...")
    outlook = win32com.client.Dispatch("Outlook.Application")
    namespace = outlook.GetNamespace("MAPI")

    print("\n=== Accounts ===")
    try:
        accounts = namespace.Accounts
        print(f"Account count: {accounts.Count}")
        for i in range(1, accounts.Count + 1):
            acc = accounts.Item(i)
            try:
                print(f"  [{i}] DisplayName={acc.DisplayName!r}  SmtpAddress={getattr(acc, 'SmtpAddress', 'N/A')!r}  AccountType={getattr(acc, 'AccountType', 'N/A')}")
            except Exception as e:
                print(f"  [{i}] Error reading account: {e}")
    except Exception as e:
        print(f"Error listing accounts: {e}")

    print("\n=== Stores ===")
    try:
        stores = namespace.Stores
        print(f"Store count: {stores.Count}")
        for i in range(1, stores.Count + 1):
            store = stores.Item(i)
            try:
                print(f"  [{i}] DisplayName={store.DisplayName!r}")
                try:
                    inbox = store.GetDefaultFolder(6)
                    print(f"       Inbox OK, ItemCount={inbox.Items.Count}")
                except Exception as e2:
                    print(f"       Inbox error: {e2}")
            except Exception as e:
                print(f"  [{i}] Error: {e}")
    except Exception as e:
        print(f"Error listing stores: {e}")

    print("\n=== Default Inbox ===")
    try:
        inbox = namespace.GetDefaultFolder(6)
        print(f"Default inbox: {inbox.Name}, store: {inbox.Store.DisplayName}, items: {inbox.Items.Count}")
    except Exception as e:
        print(f"Error getting default inbox: {e}")


if __name__ == "__main__":
    main()
