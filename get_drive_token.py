"""Private-file Drive authorization entry point; safe to import.

Install requirements-archive.txt and provide client_secret.json privately.
Uses authorize_drive's consent flow and protected token.json output, never stdout.
"""


def main():
    try:
        from authorize_drive import main as authorize
        return authorize()
    except KeyboardInterrupt:
        print('Authorization cancelled.')
        return 1
    except Exception:
        # Import errors may also contain sensitive configuration: no traceback.
        print('Authorization failed. Check local dependencies and private configuration.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
