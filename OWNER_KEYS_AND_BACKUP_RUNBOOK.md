# Owner key availability and independent backup — no values in output

## Decision

Use the available external USB drive as the first independent, encrypted,
normally disconnected second copy. Google Drive remains the primary private cold
store; neither GitHub nor the repository holds market data or signing material.
This is a destination decision, not evidence that the drive is encrypted, has
enough capacity, has the data, or has passed a restore. No settings were changed.

Historical key availability and provider retention permission remain UNKNOWN.
They do not block offline coding. They block commissioning archival of history
whose original signatures or permitted retention cannot be established.

## 1. Safe key availability check

The code's relevant exact name is `EVIDENCE_LEDGER_SIGNING_KEY`. Do not substitute
`MODEL_ARTIFACT_SIGNING_KEY`, `RUNTIME_EVIDENCE_SIGNING_KEY`, a database password,
an OAuth token, or a newly generated key. No rotation/reset is requested.
The current app loads the ledger key from server secrets/environment; its live
factory does not yet supply historical keys. An old copy must be verified against
old originals before the historical-key adapter can be commissioned.

1. Privately locate the existing Streamlit secret backups in
   Documents\TradingResearch and any password-manager ledger-key entries.
   Use File Explorer/password-manager titles and dates, not terminal content
   dumps, recursive content searches, screenshots, clipboard-sharing or chat.
   Do not move these files into the project. The agent has not read them.
2. For one saved TOML/text-format Streamlit backup, from the development folder:

   ```powershell
   .venv/Scripts/python.exe ledger_key_availability.py
   .venv/Scripts/python.exe ledger_key_availability.py --check-private-toml
   ```

   The first command is offline PREVIEW (reads/writes/network 0). The second
   prompts for ONE private absolute file path, hidden. Enter only the path,
   without quote characters; it never asks for a key value. The existing file
   must be outside the project and not a link/junction. No path/value argument
   is accepted or retained in command history. No persistent receipt is written.
3. Expected result is PRIVATE_KEY_NAME_CHECKED with `present` true/false and a
   count of nonempty exact-name string entries. It prints no values, key hashes,
   paths, database URLs or TOML contents. Invalid format/size gives a stable
   BLOCKED code; stop, do not paste the file contents for diagnosis. JSON,
   encrypted archives, screenshots and password-manager exports are not TOML.
4. Repeat only on explicitly chosen older backups, if present. Keep the source
   labels/dates privately. Multiple entries could conflict; do not combine them
   or choose one by guesswork. A nonempty entry can still be a placeholder or
   the wrong historical key: this is PRESENCE ONLY, not cryptographic proof.
5. In the password manager, check only whether ledger-key entries and older
   versions exist. Do not export the vault to plaintext or reveal values here.
   GitHub's secret-name list can show that a name is configured, not retrieve or
   prove the value. Do not alter GitHub or Streamlit secrets for this inventory.

Safe reply examples: "Current private copy found; older dated copies found;
not yet verified", "Current found; older copies unknown", or "No copies located".
Never reply with key values, private files, a connection URL or screenshots.

Later Package 3 will inventory required key IDs/schema versions read-only and
verify owner-supplied private keys against authenticated originals. Modern IDs
alone are not full historical signature verification. Schema-v1 originals lacking
an ID require the explicit `legacy-schema-v1` binding and verified signatures;
the current key is never silently substituted. Unknown/missing keys protect the
affected history; do not delete it, re-sign it or fabricate a replacement.

## 2. Prepare the USB destination — owner steps, not agent actions

First inspect Windows Settings -> System -> About -> Windows specifications for
the edition, and File Explorer -> this USB drive -> Properties for free space.
Do not format a drive, erase existing contents, reset an existing encryption key
or change permissions blindly. If it contains unbacked-up files or cannot be
unlocked reliably, stop and establish their independent backup first.

On Windows Pro/Enterprise/Education, Microsoft provides BitLocker Drive
Encryption and lists removable drives under "BitLocker To Go". Device Encryption
on Home is not evidence that an external USB drive is encrypted.
[Microsoft owner instructions](https://support.microsoft.com/en-au/windows/security/encryption/bitlocker-drive-encryption).

If BitLocker To Go is available and the drive is suitable:

1. Open Start -> type "Manage BitLocker" -> open BitLocker Drive Encryption.
2. Identify the USB by its verified drive letter and label under removable data
   drives. Stop if there is any ambiguity about the target.
3. If already encrypted, verify you can unlock it and have its recovery key;
   do not re-encrypt or replace its key. Otherwise select Turn on BitLocker
   only for that USB, after protecting any pre-existing contents.
4. Choose a strong unique unlock password. Save it and the recovery key privately
   in the password manager with an independent recovery copy. Never save the
   only recovery key on the same USB or in the public repo. Do not enable
   automatic unlocking just to make the pilot convenient.
5. Follow the wizard for a removable drive; for a previously used drive choose
   whole-drive encryption, not only used space. Wait for completion and verify
   the drive reports encryption complete. Do not unplug during encryption.
6. Safely eject, reconnect and unlock once. That proves unlock access, not yet
   restoration of the application's data.

If the edition does not offer this, do not buy/upgrade or install an unreviewed
utility on the agent's behalf. An owner-reviewed encrypted 7z archive is an
alternative; its format supports AES-256, but it requires a separate password
and a successful decryption/restore test.
[Official 7z encryption format](https://www.7-zip.org/7z.html).
We need to confirm the available tool/UI before writing its exact setup steps;
no plaintext market-data copy to an unencrypted USB is requested now.

## 3. What the second copy must contain

After retention/backup permission and encryption are verified, copy complete,
dated generations: immutable verified cold objects, manifests, authenticated
catalogue/root/rotation receipts, schema versions, reviewed code/configuration
metadata, source witnesses and consistent local-state backups. Do not overwrite
the only good generation or copy a live SQLite main file without its transaction
state: use a reviewed consistent backup/export, not Explorer on an active DB.
Keep signing/decryption credentials separately in the private password manager,
not inside a market-data bundle. Recovery must test access to both.

Verify object counts and hashes after copying and an independent restore from
the USB, including original signatures and analytical dataset identities. A file
copy, an unlock, or a checksum of one file is not whole-application recovery.
Keep the drive disconnected between owner backup/restore sessions and preferably
physically separate from the PC. The same Drive account, PC sync folder, another
folder on the same USB, or a repository artifact is not an independent copy.

Important limitation: a disconnected USB cannot receive unattended nightly
archives. It is a commissioning/emergency second copy, not an unattended service.
Before any future hot deletion, the exact objects and trusted roots needed for
that deletion must already have verified independent copies. No "copy it later"
exception. The eventual capacity model must include unreplicated history and
backup lag. If ongoing owner backup sessions are unacceptable, a separate private
storage account with independently controlled credentials is a later decision;
this package creates none and authorizes no automatic deletion.

## 4. Retention terms — record permission, do not infer it from storage capacity

Privately locate the actual applicable Upstox/exchange/data agreement and its
version/effective date, or obtain written clarification from the provider.
Record whether it permits: personal research history, derived features/evidence,
ML training, raw quotes/depth/candles, private Drive storage, a private encrypted
offline backup, retention length, and what must happen when access ends.
Use existing public licence/acknowledgement instructions; an acknowledgement
variable and a successful API call are not proof of these permissions.

Only a permission summary is needed in chat: VERIFIED_ALLOWED / VERIFIED_LIMITED
with the applicable limit, or UNKNOWN. Do not upload private contract/account
documents. Do not assume indefinite retention, public redistribution or a second
backup is allowed. No new retention window or deletion schedule is activated by
this document. Frozen 2025/2026 data stays unexamined and protected; if a licence
conflicts with preservation requirements, stop for an explicit reviewed decision.

## Reply needed before commissioning (not before continuing offline work)

- Key copies: current found / older found / unknown / not found; not values.
- USB: edition supports encryption / encrypted and unlock tested / setup pending;
  available capacity only, no serial/account/recovery-key screenshots.
- Provider permissions: allowed / limited / unknown, with a public source or a
  private written-permission summary where available.

No hosted setting, credential, existing data or installed capture file was changed
to prepare this runbook or the presence checker.
