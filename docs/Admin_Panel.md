# Admin Panel Guide

The PaperVisor Admin Panel provides tools for managing your library, users, and system configuration. It is accessible to users with the `Is Admin` role.

The panel is divided into 7 tabs:

1.  **Patterns:** Manage library folder structures.
2.  **Library:** Scan and update library content.
3.  **Maintenance:** clean up data and enrich metadata.
4.  **OPDS:** Configure remote access feeds.
5.  **API:** Manage external metadata provider keys.
6.  **Users:** Manage user accounts and roles.
7.  **Logs:** View system events and security audit trails.

---

## 1. Patterns Tab

**Purpose:** Define how PaperVisor recognizes and parses your files.

*   **Library Definitions:** Map filesystem paths to PaperVisor libraries.
*   **Regex Patterns:** Configure regular expressions to extract metadata (Author, Series, Title) from filenames.
*   **Test Playground:** Test your regex patterns against sample filenames to ensure they work as expected.

---

## 2. Library Tab

**Purpose:** trigger core library scanning operations.

*   **Scan Library:** specific libraries to scan for new or changed files.
*   **Force Rescan:** Ignore modification times and force a full re-read of file metadata.
*   **Ignore List:** Manage files or folders that should be skipped during scanning (e.g., system files, temporary folders).

---

## 3. Maintenance Tab

**Purpose:** Optimize the database and enrich content metadata.

### System Maintenance
*   **Clean Libraries:** Sync the database with the filesystem. Removes entries for deleted files, finds orphaned media, and removes empty directories. *Recommended: Run uniformly.*
*   **Regenerate Thumbnails:** Re-create PDF thumbnails. Useful if you've changed thumbnail settings or if some images are corrupted.

### Metadata Enrichment
*   **Extract EPUB Covers:** Extract cover images embedded within EPUB files.
*   **Fetch DOI Metadata:** Automatically fetch metadata (Title, Author, Abstract, etc.) for academic papers using their DOI identifiers. Sources: CrossRef, Semantic Scholar, PubMed.
*   **Fetch ISBN Metadata:** Automatically fetch book metadata and covers using ISBN identifiers. Sources: OpenLibrary, Google Books.

### Advanced / Danger Zone
*   **User Data Cleanup:** Remove data left behind by deleted users. *Always run with "Dry Run" enabled first.*

---

## 4. OPDS Tab

**Purpose:** Configure the Open Publication Distribution System (OPDS) server for remote access.

*   **Feed Settings:** Enable/disable the OPDS server.
*   **Authentication:** Set up API keys for OPDS clients.
*   **Feed URL:** Get the URL to use in your e-reader app (e.g., Moon+ Reader, Librera).

---

## 5. API Tab

**Purpose:** seamless integration with external metadata providers.

*   **Provider Keys:** Enter API keys for services like Google Books, Springer, or Semantic Scholar to increase rate limits and access premium data.
*   **Provider Status:** Check the connectivity and quota status of connected services.
*   **Diagnostics:** Run connection tests to verify provider health.

---

## 6. Users Tab

**Purpose:** Manage user access and permissions.

*   **User List:** View all registered users.
*   **Create/Invite:** Add new users manually or generate invite links.
*   **Roles:** Assign `Admin` or `User` roles.
*   **Edit User:** Update usernames, emails, or reset passwords.
*   **Delete User:** Permanently remove a user account.

---

## 7. Logs Tab

**Purpose:** Monitor system health and security.

*   **System Logs:** View server application logs for debugging and error tracking.
*   **Audit Trail:** View security-critical events such as:
    *   Successful/Failed logins.
    *   User creation/deletion.
    *   Permission changes.
    *   Unauthorized access attempts.
