## MODIFIED Requirements

### Requirement: Iraqi legal-source web search

`legal_search.py` SHALL expose `search_moj`, `search_dijlex`, `search_ur_portal`, `search_national_library`, and `search_all` for querying Iraqi legal sources. Each function SHALL accept a query and optional `max_results_per_source` and return a list of `SearchHit` dataclass instances. All HTTP fetching SHALL go through a `_fetch_html(url)` / `_post_html(url, data)` seam that validates the URL's host against a frozen `_ALLOWED_HOSTS` allowlist (`moj.gov.iq`, `www.moj.gov.iq`, `dijlex.com`, `www.dijlex.com`, `urportal.ur.gov.iq`, `www.urportal.ur.gov.iq`, `nlb.gov.iq`, `www.nlb.gov.iq`) and raises `LegalSearchBlockedError` on mismatch. HTTP clients SHALL be constructed with `follow_redirects=False`; 3xx responses SHALL be manually resolved by re-validating the `Location` header against the allowlist and re-issuing (max 3 hops). `search_ur_portal` SHALL cap each `<script type="application/ld+json">` content length at 1 048 576 bytes before `json.loads`, skipping oversized scripts.

#### Scenario: search_all returns hits from all sources
- **GIVEN** `search_all` is called with `query="القانون المدني"` and `max_results_per_source=5`
- **WHEN** all sources respond successfully
- **THEN** a list of `SearchHit` instances is returned, each with `url`, `title`, `snippet`, and `source` fields

#### Scenario: a non-allowlisted host is refused
- **GIVEN** `_fetch_html` is called with `url="http://evil.example.com/page"`
- **WHEN** the URL is validated
- **THEN** `LegalSearchBlockedError` is raised and no HTTP request is made

#### Scenario: a cross-domain redirect is blocked
- **GIVEN** `_fetch_html` issues a request to `moj.gov.iq/search` and the server responds with `302 Location: http://evil.example.com/result`
- **WHEN** the redirect is resolved
- **THEN** `LegalSearchBlockedError` is raised (the redirect target is not in `_ALLOWED_HOSTS`) and no request is made to `evil.example.com`

#### Scenario: an HTTP-to-HTTPS redirect on the same host is followed
- **GIVEN** `_fetch_html` issues a request to `http://moj.gov.iq/search` and the server responds with `301 Location: https://moj.gov.iq/search`
- **WHEN** the redirect is resolved
- **THEN** the redirect target is validated against `_ALLOWED_HOSTS` (passes) and the HTTPS request is issued

#### Scenario: an oversized JSON-LD script is skipped
- **GIVEN** `search_ur_portal` encounters a `<script type="application/ld+json">` whose content is 2 MB
- **WHEN** the page is parsed
- **THEN** that script is skipped (not `json.loads`ed) and the search continues with other scripts on the page
