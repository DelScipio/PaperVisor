# PaperVisor

Self-hosted library manager for **papers and books**, thoughtfully designed and built with NiceGUI.

PaperVisor is designed to be your central hub for managing academic papers, books, and comics. It provides a robust web interface to import files, organize them efficiently, enrich their metadata automatically, read them directly in the browser, and share your libraries with other users. It also exposes a fully-featured **OPDS 1.2** catalog, making it the perfect backend for e-readers and compatible apps.

## ✨ Core Features

### 📖 Reading & Organization
- **Native Web Readers**: First-class, built-in readers for **PDF (via PDF.js)**, **EPUB**, and **CBZ**.
- **Progress Tracking**: Automatically remembers your last read location, tracks "Continue reading" states, and marks files as completed.
- **Powerful Curation**: Organize your library using **Markers** (both manual and smart rules), **Tags**, **Favorites**, and a dedicated **To Read** list.
- **File Naming Patterns**: Configurable naming patterns per library and file type, complete with batch renaming and migration helpers.

### 🔌 OPDS 1.2 Catalog Support
- Fully compliant OPDS 1.2 feed for seamless integration with e-readers (like Boox) and apps.
- Canonical OPDS reorder facets: `newest`, `oldest`, `az`, `za`, `popular`, `author`.
- Collection filter facets across top-level feeds: `All Files`, `Academic Papers`, `Books`.
- **Per-user API Keys** with secure regeneration and revocation.
- Reverse-proxy awareness for safe external access.
- Flexible browsing by author, series, genre, journal, and year.

### 🤖 Smart Metadata & Enrichment
- **Automated DOI Extraction**: Seamlessly extracts DOIs from PDFs and fetches metadata via **Crossref**, with fallbacks to Semantic Scholar and PubMed.
- **Automated ISBN Detection**: Sniffs out ISBNs from filenames, PDFs, and EPUBs, populating book metadata via **OpenLibrary** and **Google Books**.
- **Automatic Covers**: Automatically fetches and generates gorgeous cover thumbnails for your documents.
- **Admin Diagnostics**: Built-in tools for testing metadata provider health and configuring dynamic fetch timeouts.

### 👥 Multi-User & Library Management
- **Multiple Libraries**: Organize content into distinct libraries with Private, Shared, or Global scopes.
- **Access Control & Sharing**: Invite other users with granular Reader or Editor permissions, securely transfer library ownership, and utilize an Inbox system.
- **Admin Dashboard**: Comprehensive admin tools for user management, including creation, deletion, password resets, and registration toggles.
- **Security & Audit Logs**: Detailed, UI-accessible audit trails for monitoring security events like failed logins, rate limit triggers, and system access.

---

## 📚 Documentation
- OPDS details: [docs/OPDS Spec.md](docs/OPDS%20Spec.md)
- Boox setup: [docs/Boox.md](docs/Boox.md)

---

## 🚀 Getting Started

### Run via Docker (Recommended)
PaperVisor defaults to a robust SQLite (`papervisor.db`) database. For deployment, mounting the database file and the `library_files/` directory as volumes is recommended.

**Docker Compose (Unraid Friendly)**
An Unraid-friendly compose file is included: [`docker-compose.yml`](docker-compose.yml)
```bash
docker compose up -d
```
Then navigate to `http://localhost:8080`.

**Standard Docker Run**
```bash
docker run --rm -p 8080:8080 \
  -e PAPERVISOR_STORAGE_SECRET="change-me" \
  -v "$PWD/papervisor.db:/app/papervisor.db" \
  -v "$PWD/library_files:/app/library_files" \
  pmmsoares/papervisor:latest
```

*Note: The container automatically runs database migrations (`alembic upgrade heads`) at startup. You can disable this by setting `PAPERVISOR_RUN_MIGRATIONS=0`.*

### Run Locally (Development)
```bash
cd /home/pmmsoares/Documents/Python/PaperVisor
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

**Development Extras**
```bash
pip install -r requirements-dev.txt
# Run type checking
mypy
```

### Testing
```bash
# Run all tests
python -m pytest

# Run focused OPDS/FastAPI tests
python -m pytest -q tests/test_opds_gen.py tests/test_opds_mock.py tests/test_fastapi.py
```

### Database Management
To apply manual Alembic migrations locally:
```bash
/home/pmmsoares/Documents/Python/PaperVisor/.venv/bin/alembic revision --autogenerate -m "your message"
/home/pmmsoares/Documents/Python/PaperVisor/.venv/bin/alembic upgrade head
```

### Security Environment Flags

- `PAPERVISOR_REQUIRE_STORAGE_SECRET=1`  
  Fail startup when no storage secret is configured (recommended for production).
- `PAPERVISOR_STORAGE_SECRET=...`  
  Explicit storage/session secret used by NiceGUI.
- `PAPERVISOR_OPDS_ALLOW_QUERY_KEY=0|1` (default: `0`)  
  Controls whether OPDS auth via `?key=...` is accepted.
- `PAPERVISOR_API_ALLOW_QUERY_KEY=0|1` (default: `0`)  
  Controls whether REST API auth via `?api_key=...` is accepted.
- `PAPERVISOR_TRUST_FORWARDED=0|1` (default: `0`)  
  Enables use of `X-Forwarded-*` headers for OPDS base URL generation.
- `PAPERVISOR_ALLOWED_FORWARDED_HOSTS=host1,host2`  
  Optional allowlist applied when forwarded headers are trusted.
- `PAPERVISOR_MAX_PDF_UPLOAD_BYTES` (default: `524288000`)  
  Max size for annotated PDF uploads (`/api/v1/papers/{id}/save_pdf`).
- `PAPERVISOR_MAX_STREAMED_FILE_BYTES` (default: `1073741824`)  
  Max file size served by reader/raw endpoints.
- `PAPERVISOR_FILE_ACCESS_CACHE_TTL_S` (default: `2.0`)  
  TTL for cached file-access authorization checks.
- `PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS=0|1` (default: `0`)  
  Allow app startup even if Alembic upgrade fails (recovery mode only).

---

## 🐳 Docker Building & Publishing

You can build and tag the Docker image manually:
```bash
docker build \
  -t pmmsoares/papervisor:latest \
  -t pmmsoares/papervisor:git-$(git rev-parse --short HEAD) \
  .
```

Publishing to Docker Hub:
```bash
docker login
docker push pmmsoares/papervisor:latest
docker push pmmsoares/papervisor:git-$(git rev-parse --short HEAD)
```
