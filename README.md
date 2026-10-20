# PataMahali — Kenya property discovery and listings

A mobile-first Flask + SQLite property marketplace for rentals, hotels and short stays, shops and offices, warehouses, land and properties for sale. It is designed to help a visitor move from a broad search to a county, constituency, ward or specific neighbourhood—and to help landlords and authorised agents advertise property with exact location details.

## What is included in this upgrade

- **A fuller public homepage:** improved image-led sections, direct category buttons, county shortcuts, a general search, owner entry points and a clear distinction between illustrative images and real live adverts.
- **All 47 counties and 290 constituencies:** a searchable location directory with about 1,295 curated local-area names, including fine-grained property-search names for Nairobi, Kiambu, Mombasa, Nakuru, Kisumu, Kilifi, Kwale, Kakamega, Bungoma, and the other counties. Nairobi and Kiambu have ward-level lists built into the catalogue. Locality aliases are neighbourhood/search names, not assertions that every alias is an official electoral ward.
- **A guided landlord location form:** county → constituency → ward/town/neighbourhood, plus a free-text field for the exact estate, road, stage, apartment block or landmark. Landlords can include the direct original advert or booking URL from another website.
- **External property discovery:** place pages and empty search results link to Google searches restricted to BuyRentKenya, Property24 Kenya and Jiji Kenya. They open external sources rather than copying those sites' photos, prices or adverts. When an owner attaches a direct advert URL, the public detail page can open that original advert.
- **Real listing protections:** the platform does not invent available houses. A listing appears as live only after partner identity, payment, property and administrator approval checks pass. Homepage photography is illustrative, not an advertised property.
- **Paid visibility options:** owners can request VIP or VVIP placement for an eligible live listing and submit a payment reference. The administrator manually checks payment under **VIP / VVIP boosts** before activating the chosen tier. Default starter pricing is KES 1,000 for 7 days (VIP) and KES 2,500 for 14 days (VVIP); the administrator can change both amounts and durations in Site & Fees. VVIP ranks above VIP, and VIP ranks above standard listings while the paid promotion is active.
- **Search-engine foundations:** crawlable county and constituency pages, page titles/descriptions and canonicals, structured WebSite/CollectionPage metadata, `robots.txt`, a dynamic `sitemap.xml` and an `llms.txt` overview. Fine-area pages stay accessible through the location directory, but empty generated locality pages are not pushed into the sitemap or index; a locality can become indexable once a real public listing supports it.
- Existing partner accounts, property review and enquiry workflows, map links, admin controls, backups and restore tools, settings, branding, and payment instructions remain in the project.

## Run locally

Python 3.12 is recommended. Install dependencies in a virtual environment and start the app:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000/`.

## Render deployment

1. Upload the project folder contents to the GitHub repository used by your Render service.
2. In Render, deploy the existing web service or create a Blueprint from `render.yaml`. The Blueprint configures Gunicorn and a 1 GB persistent disk at `/var/data`; persistent storage is important for the SQLite database, uploads and session key.
3. Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in Render. Use a strong unique admin password of at least 12 characters. Do not commit credentials to GitHub.
4. Deploy. The admin entry is `/promise212324` and the management pages live under `/manage-admin/`.
5. In admin **Site & Fees**, set the final site name, public HTTPS base URL/domain, listing charges, payment instructions, support contacts and any other public settings. Confirm the custom domain is attached and redirects to HTTPS.
6. Before accepting paid advertisements, test partner registration, one listing from submission through manual payment/identity/property review, and one full backup/restore on a safe copy.

If the service was created manually and not from `render.yaml`, check that a persistent disk is mounted at `/var/data`. Without it, temporary fallback storage can be lost after a restart or redeploy.

## Make Google able to discover the site

After the public domain is attached and set in Site & Fees:

1. Add and verify the domain in **Google Search Console**.
2. Submit `https://YOUR-DOMAIN/sitemap.xml` in Search Console. The app also exposes `https://YOUR-DOMAIN/robots.txt` and `https://YOUR-DOMAIN/llms.txt`.
3. Use URL Inspection for the homepage, `/places`, several county pages and several constituency pages. Ask Google to recrawl the pages after the public domain is configured.
4. Keep the website useful: get real local landlords to add accurate properties, original photos, exact area names, current prices and honest availability. Do not describe illustrative imagery as available homes or copy another portal's listings. Search engines decide whether and when to index pages; submitting a sitemap is a discovery signal, not a guarantee of ranking or immediate appearance.

The directory can be searched by names like Runda, Ruaka, Kimbo, Kabuku, Diani, Nyali, Mtwapa, Naivasha, Eldoret, Kisumu and local names across the other counties. If an estate or small locality is not already on the selector, an owner can still type it in the exact local area field. Once that listing is approved and public, the locality is eligible to appear as its own linked area page.

## Admin workflow for an owner listing

1. The owner/host/authorised agent registers and submits required identity details.
2. The owner enters a precise county/constituency/locality, adds genuine photos and the property facts, and submits the listing fee reference.
3. The administrator independently checks the payment, partner identity and authority to advertise; checks the location and photos; then approves and publishes the property.
4. For paid priority, the owner opens **Boost visibility**, chooses VIP or VVIP and submits the payment reference. An administrator verifies the actual payment and activates or rejects the request under **VIP / VVIP boosts**.
5. Keep availability current. Expired or unconfirmed listings are not presented as current public stock.

## Important notes

- The 1,295 locality names are a curated first-pass directory, not an authoritative exhaustive list of every street, estate, ward, apartment block and village in Kenya. The owner-entered exact-local-area field prevents the catalogue from blocking communities not listed yet.
- The application has no preloaded real property inventory in this ZIP. Public listing cards will fill as genuine properties are added and approved.
- A direct external advert URL is optional. External source-search shortcuts open those portals through Google; they do not certify the advertiser, guarantee that a particular property is still available, or mirror a portal's data.
- VIP/VVIP status controls placement inside this platform only; it does not promise a sale, enquiry volume or a higher ranking in Google.
