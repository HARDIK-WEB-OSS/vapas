# Privacy design

Status: M2, 20 Nov 2026. VAPAS acts as a Data Fiduciary under the Digital Personal Data Protection Act, 2023 (DPDP Act) and the DPDP Rules, 2025.

Legal references in this file describe our understanding, not legal advice. Items marked **[verify]** must be checked against the official Act and Rules text (published on meity.gov.in and in the Gazette of India) before the pilot (M10). That includes which obligations are already in force: the Rules commence in phases.

## 1. Data inventory

| Data | Where | Protection | Retention |
|---|---|---|---|
| Email address | `users.email` | Plain text (needed for login and email); RLS | Until account deletion |
| Password | `users.password_hash` | Argon2id hash only | Until account deletion |
| Per-user data key | `user_keys.wrapped_dek` | Wrapped by the master key (AES-256-GCM) | Until account deletion (then crypto-shredded) |
| Sessions | `sessions` | Refresh tokens stored as SHA-256 hashes only | Revoked sessions kept until account deletion |
| Email links | `email_tokens` | SHA-256 hashes only; 24 h (verify) or 1 h (reset) expiry; single use | Until account deletion |
| Consent records | `consents` | RLS; tied to the exact notice version | Until account deletion |
| Audit log | `audit_log` | Append-only; IP stored only as a keyed hash; no statement content | Kept after deletion with the user id removed (see section 5) |
| Raw statement files (M3) | Object storage `raw/{user_id}/` | Private bucket; presigned upload only | Deleted within 1 hour |
| Transactions (M3) | `transactions` | Narration and references encrypted with the user's data key | 13 months after transaction date |
| Findings and cases (M5, M7) | Postgres | Encrypted snapshots | Until the user deletes them or the account |

Rate-limit counters in Redis are keyed by a SHA-256 of the email or IP, never the raw value.

## 2. Notice and consent

- The notice text lives in `backend/src/vapas/privacy/notice_texts/` (English and Hindi) and is published to `consent_notices` by a migration together with its SHA-256. A published version is never edited; a change means a new version and a new migration.
- Signup requires the client to send the version of the notice the user was shown. If it is not the current version, signup is refused (HTTP 409) so nobody consents to text they did not see.
- One purpose in v1: `statement_analysis`. Processing of statements (M3 onwards) checks that this consent is active.
- Withdrawal: `POST /account/consent/withdraw`. From then on no new statement is processed. The user is offered deletion.
- Notice v1 (2026-11-v1) is a working draft. Before the pilot: legal review, a grievance contact, and a native-speaker check of the Hindi text, published as v2. **[verify]** the required notice contents under the Rules.

## 3. Purpose limitation

- Data is used only to detect late reversals and related items, calculate compensation under verified RBI rules, and help the user draft complaints.
- No advertising, no sale, no model training on user data.
- Statement text never goes to a hosted model (ADR 0005). Only redacted letter text may be sent for wording polish.
- Analytics events (M10) carry no personal data.

## 4. Rights: access, correction, erasure

- **Export**: `GET /account/export` returns all of the user's data as JSON (`format_version` 1): profile, consents, sessions (without token hashes) and the audit log. From M3 on it includes statements metadata and retained transactions; from M5 it includes findings with their decrypted snapshots, so the export stays complete after old transaction partitions are dropped.
- **Erasure**: `DELETE /account` with password re-entry. In one request:
  1. every object under the user's storage prefixes is deleted;
  2. an `account_deleted` audit event is written;
  3. the user row is deleted, which cascades to keys, sessions, email tokens and consents (and, from M3, statements, transactions, findings and cases).
  If storage deletion fails, the database is untouched and the user gets an error to retry, so there is never a database deletion with files left behind.
- **Correction**: email change and locale change arrive with the settings page (M8).
- **Grievance**: a grievance contact and response process are required before the pilot. **[verify]** response timelines in the Rules.

## 5. What stays after deletion

- Audit events stay for security and accountability, with `user_id` set to NULL, so they no longer link to any person. They contain no email, no IP (only a keyed hash that cannot be reversed without the server key), and no statement content.
- Backups: deleted data can remain in database backups until they expire (backup retention set in M9, target 7 days). Encrypted fields in backups are unreadable after deletion because the user's data key is gone (crypto-shredding). Plain fields (email) remain until the backup expires; that window is stated in the privacy policy.

## 6. Encryption and key management

- Each user gets a random 256-bit data key (DEK) at signup. Only the wrapped form is stored: AES-256-GCM under a master key (KEK) from the environment (`KEK_KEYS`, `KEK_ACTIVE_VERSION`). The wrap is bound to the user id and KEK version, so a wrapped key cannot be moved to another user.
- Field encryption uses a key derived from the DEK (HKDF-SHA256), AES-256-GCM, a random 96-bit nonce per value, and associated data binding the ciphertext to the user and the field. A ciphertext copied to another field or user fails to decrypt.
- Equality lookups (UTR/RRN matching) use a per-user HMAC blind index derived from the DEK, never plain values.
- The app refuses to start in staging or production with any of the example secrets from `.env.example`.

### Key rotation plan

1. Generate a new 32-byte KEK and add it to `KEK_KEYS` under the next version number; keep the old one.
2. Set `KEK_ACTIVE_VERSION` to the new version and deploy. New users are wrapped with the new KEK; existing wrapped keys still unwrap with the old one.
3. Run a re-wrap job (built in M9 on top of the tested `KeyRing.rewrap`): for each user, unwrap with the old KEK and wrap with the new one, in batches, recording `rotated_at`. Data is not re-encrypted; only DEKs are re-wrapped.
4. When no `user_keys.kek_version` points to the old version, remove it from `KEK_KEYS` and deploy.
- Rotate on schedule (yearly) and immediately if a KEK may have leaked.
- `JWT_SECRET` rotation logs every user out (all access tokens become invalid; refresh tokens still work because they are opaque and stored in the database).

## 7. Breach-notification process

1. **Detect**: alerts (Sentry, failed-login spikes, refresh-token reuse events, unexpected RLS errors, object-store access anomalies) go to the on-call person (Hardik in the pilot).
2. **Contain**: revoke affected sessions (`revoke_all_sessions`), rotate exposed secrets (JWT secret, database passwords, object-store keys; KEK rotation as above if a KEK may be exposed), block the attack path.
3. **Assess**: what data, which users, encrypted or not, time window. Keep a written timeline.
4. **Notify**: our understanding is that the Rules require informing each affected user and the Data Protection Board of India without delay, with a detailed report to the Board within 72 hours of becoming aware. **[verify]** the exact content and timelines in the Rules.
   - User message: what happened, likely consequences, what we did, what the user should do, contact.
   - The breach is recorded even if it later proves minor.
5. **Review**: root cause, fix, regression test, update `docs/threat_model.md`.

## 8. Children

VAPAS is for adults with their own bank accounts. Sign-up asks users to confirm they are 18 or older (added in M8). **[verify]** the verifiable parental consent rules for anyone under 18.
