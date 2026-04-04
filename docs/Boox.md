# Boox (Onyx) OPDS Setup (PaperVisor)

This guide covers the recommended OPDS configuration for Boox devices.

## 1) Prerequisites

- PaperVisor is reachable from the Boox (same LAN or public URL).
- You have a PaperVisor user account.
- You have generated an OPDS API key in Profile → OPDS.

## 2) OPDS URL

Use your personal API key URL:

```
https://<your-domain>/opds/?key=YOUR_API_KEY
```

Notes:
- Use `https://` for production.
- Each user has their own key and sees only their content.

## 3) Boox configuration steps

On the Boox, add a 3rd-party OPDS catalog:

- **Catalog URL**: `https://<your-domain>/opds/?key=YOUR_API_KEY`
- Save and connect

## 4) Troubleshooting

- **401 Unauthorized**: Ensure the API key is included in the URL.
- **Missing covers**: Confirm `/library_files/` is accessible and cover files exist.
- **Download issues**: Verify file links point to `/library_files/...` and not a reader URL.
- **Browse By shows empty lists**: Boox is strict about OPDS link kinds.
	- Menu entries that open another menu must use `kind=navigation`.
	- Entries that open books/papers must use `kind=acquisition`.
	- Quick check: open `/opds/browse?key=YOUR_API_KEY` in a browser and inspect `<link rel="subsection" ... type="application/atom+xml;profile=opds-catalog;kind=...">`.
	- If metadata was recently fixed server-side, remove and re-add the catalog on Boox to clear cached feed structure.

---

If you need help diagnosing a specific setup, provide:

- The exact OPDS URL entered on the Boox
- Whether you’re using a reverse proxy (and which)
- A snippet of server logs for a failed connection attempt
