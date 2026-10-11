# PataMahali — deployable verified property marketplace

A responsive Flask + SQLite marketplace starter for rental homes, short stays, shops/business premises, warehouses/industrial spaces, land and properties for sale. The brand is a placeholder: the administrator can change the public site name, tagline, colors, contact details, fees, payment instructions, public domain and the partner management-site link.

## Included

- Minimal animated welcome screen with just two primary choices: Find a place or List a property. Public search uses compact two-column mobile / three-column desktop cards.
- Property detail pages, real image uploads, landmarks, stored coordinates, Google Maps directions, interest requests and “report taken” flow.
- Partner accounts for owners, agents, hosts and commercial-property providers; private ID/passport front/back uploads; reusable partner profiles.
- Configurable category listing charges. A payment reference does **not** itself count as verified payment. An administrator must reconcile it, verify the partner, and separately approve/check the property before it can publish.
- `Visit my management` button on the partner pages. Admin can connect it under Site & Fees; when no URL is configured, it opens a friendly placeholder page.
- Admin entry path is hard-coded at `/promise212324`. Admin tools cover listings, payment confirmation, verification, partner accounts, enquiries, taken-listing reports, settings, traffic analytics, and full SQLite download/restore.
- Explicit opt-in device location for nearby sorting. Only approximate coordinates rounded to three decimal places are stored for visitor analytics; no IP addresses are stored. Browsers do not reveal a phone number automatically: deduplication uses the browser key, and a provided/registered phone or account can reconcile visits across browsers.
- Platform and property QR codes, configurable public logo (including favicon/PWA branding), manifest, installable PWA shell with cache version refresh, offline fallback warning, dynamic sitemap and robots.txt. The landing counter gently animates to the recorded unique browser/account/voluntarily provided phone total; it does not fabricate visitors.
- Optional campaign placement inside search results, managed from Site & Fees: image, short message, destination link, or a safely embedded public YouTube/Vimeo video. It never turns the two-choice welcome screen into a pop-up.
- Typo-tolerant search fallback for likely spelling mistakes, budget widening, optional GPS-nearby sorting, in-page route preview and turn-by-turn Google Maps directions from current location or a typed landmark.
- SQLite snapshot backups, daily automatic snapshots (14 retained), manual backup creation, download, and validated restore with a safety backup first.

## Local run

Requires Python 3.12 recommended.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000/`.

The admin login is at `http://127.0.0.1:5000/promise212324` (fixed path). Set only `ADMIN_USERNAME` and `ADMIN_PASSWORD` in Render **before first startup**. The app generates and stores its Flask session signing key on the persistent disk. The seeded admin user's display name is the configured username; use that as the administrator username at sign-in.

Copy `.env.example` to `.env` for your own notes if you use a local environment loader; the application itself reads operating-system environment variables and does not automatically load `.env`. Never commit real secrets.

Example development environment:

```bash
# Linux/macOS
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD='a-long-unique-password-here'
python app.py
```

Set a password of at least 12 characters for the administrator. The site can also change the current admin password under Site & Fees.

## Render deployment

1. Upload this folder's contents to a new GitHub repository.
2. In Render, create a **Blueprint** from the repository and review the `render.yaml` before accepting it. It configures a Starter web service and a 1 GB persistent disk. A persistent disk is required for dependable SQLite/file persistence and is a paid Render feature; check Render's current pricing before creating the service.
3. Render asks you to set just `ADMIN_USERNAME` and `ADMIN_PASSWORD`. The admin route is hard-coded as `/promise212324`; the persistent disk is mounted at `/var/data`, where the app generates and stores its session key automatically. No other manual environment variables are required.
4. Deploy. Admin URL: `https://YOUR-RENDER-SERVICE.onrender.com/promise212324`.
5. Under administrator **Site, pricing & connections**, configure the final brand name, fees, M-Pesa details, public base URL once your domain is attached, support contacts, and the second property-management website URL.
6. Attach your actual domain in Render when ready. The app generates QR and sitemap URLs using the configured public base URL or current host. If domain settings change, update `public_base_url` in admin and check QR links.
7. Download a full backup after major configuration changes and keep a copy away from the Render account. Test restoration before you put real client data into production.

The Blueprint mounts a persistent disk at `/var/data`. The app uses this path automatically on Render and falls back to local `instance/` for local development.

## Admin workflow

1. Review identity documents under Partners; verify only after checking identity and relevant authority evidence.
2. Under Properties, reconcile the actual payment reference and mark the payment confirmed.
3. Verify the property details, photos, coordinates and appropriate evidence of authority to advertise. Then choose “Verify property + publish”. That action is blocked unless the payment is confirmed, partner verified, coordinates present, and a photo exists.
4. Resolve house-seeker reports under Reports. A report hides an available listing; only an administrator may reinstate it.
5. Set correct charges and verified payment instructions under Site & Fees before public launch.
6. When the separate property management system is ready, paste its full HTTPS URL under “External property management site”. “Visit my management” will redirect to that site.

## Important production notes / limitations

- Social account buttons are optional and administrator-configurable. The public homepage intentionally keeps only the two main entry choices.
- This starter does not automatically scrape or repost homes from social media. Add real property content only with appropriate owner/agent authorization; any demo property information should be clearly labelled as illustrative until it is verified.

- **Payment verification is manual in this release.** The system records the M-Pesa/payment reference and an admin action. Automatic Safaricom M-Pesa verification requires your own Daraja app credentials, callback URL and testing; no payment is represented as verified without an admin confirmation.
- **Verification is an operational process, not magic.** The site cannot autonomously prove that a house exists or that an uploader has legal authority. An authorized team must review evidence and/or inspect properties before marking them verified.
- **Identity and precise location are sensitive.** Partner documents are stored outside public static folders and served only through authenticated admin routes. For launch, configure a persistent disk with restricted access, enforce strong admin credentials, document retention/deletion rules, HTTPS, and Kenya data-protection compliance. Consider off-site encrypted backups for uploads as well as the database.
- SQLite backups include the database records, not the binary image/ID upload folders. To recover the complete installation after storage loss, back up the `uploads/` and `private_documents/` folders as well as the SQLite file. This package's admin export is a full SQLite data backup, and restore validates the uploaded SQLite database and snapshots the previous database first.
- Listing fee defaults are editable starter values, not finalized business prices. Featured fees are shown/configurable but featured placement is not automatically applied in this release.
- Search-engine-ready URLs, sitemap, metadata and structured crawl hygiene are included, but ranking is not guaranteed. Real listing volume, unique property information, performance, Search Console configuration and ongoing content work still matter.
- The management-site link is an integration point only; tenant ledgers, e-invoices and rent receipts belong to the separate system you described and are not implemented inside this marketplace package.
- The PWA caches public navigation pages only, never partner/admin screens. Offline listing pages can be stale, so an offline banner warns that availability must be rechecked online.

## Render environment variables

Only two values need to be entered manually:

| Variable | Purpose |
|---|---|
| `ADMIN_USERNAME` | Administrator username created during first startup. |
| `ADMIN_PASSWORD` | Strong administrator password created during first startup; set before the database is initialized. |

The admin URL is fixed at `/promise212324`. Do not add `ADMIN_PATH`, `DATA_DIR`, `SECRET_KEY`, or `COOKIE_SECURE` yourself. The Render disk and application handle storage and session key setup.

## Before public launch

Verify the final brand/domain legally; set actual payment recipient details and charges; set up persistent storage and encrypted off-site backups; change the admin password; conduct an identity/property verification trial; test payment reconciliation, listing expiry, taken-report reversal and restore; add appropriate privacy, terms, retention, refund, and complaints policies; and verify the production routes with real devices.
