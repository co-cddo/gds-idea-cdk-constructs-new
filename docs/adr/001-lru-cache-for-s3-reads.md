# ADR-001: Use LRU cache for S3 reads in serve Lambda

## Status

Accepted

## Context

The StaticSite serve Lambda proxies every request through to S3. For a site with moderate traffic, this means repeated S3 GET API calls for the same files (index.html, style.css, etc.) on every warm invocation. S3 GETs are cheap individually but add latency (~50-100ms per call) and cost at scale.

We needed a caching strategy that:
- Reduces S3 API calls for frequently accessed files
- Doesn't add complexity or external dependencies (Redis, ElastiCache)
- Works within Lambda's execution model (stateless between cold starts, stateful within warm invocations)

## Options Considered

### Option A: `functools.lru_cache` (no TTL)

Python stdlib. Caches by function arguments. Cache lives as long as the Lambda execution environment. No expiry mechanism.

### Option B: `cachetools.TTLCache` (with TTL)

Third-party library (available via cognito-auth transitive dependency). Cache entries expire after a configurable time (e.g., 5 minutes). Guarantees bounded staleness.

### Option C: No caching (always read from S3)

Simplest. Every request hits S3. No staleness risk.

### Option D: Cache only hashed assets (skip HTML)

Only cache files whose filenames contain hashes (e.g., `app.3f2a1b.js`). These never change. HTML always reads from S3 (since it changes on rebuild).

## Decision

**Option A: `functools.lru_cache` with configurable `maxsize`.**

Reasons:
1. **Simplicity** — stdlib, no extra dependencies, one decorator
2. **Consistency** — same pattern used in `gds-idea-auth/static_website_access_control` Lambda (team familiarity)
3. **Lambda lifecycle bounds staleness** — execution environments are recycled periodically (minutes to hours), which naturally invalidates the cache
4. **HTTP headers handle browser-side** — `Cache-Control: max-age=0, must-revalidate` on HTML means browsers always revalidate, so once the Lambda recycles, users get fresh content immediately
5. **Configurable** — `CACHE_MAX_SIZE` env var allows tuning per deployment

## Consequences

### Positive

- Reduced S3 GET calls for warm Lambda invocations (majority of requests)
- Lower latency for cached responses (~0ms vs ~50-100ms for S3 read)
- Lower S3 API costs at scale
- No infrastructure to manage (no Redis/ElastiCache)

### Negative

- **Staleness after rebuild**: After the build Lambda uploads new content, the serve Lambda may serve cached (old) content until its execution environment is recycled. Typically seconds to minutes.
- **404 caching**: If a file doesn't exist, the `None` return is cached. A newly created file won't be served until the environment recycles.
- **Memory usage**: Each cached file consumes Lambda memory. Bounded by `maxsize` (default 128 files).

### Mitigations

- Sites that rebuild frequently (hourly or less) naturally have short staleness windows
- Lambda environments under low traffic recycle quickly
- `CACHE_MAX_SIZE` can be reduced for memory-constrained deployments
- A future enhancement could clear the cache when the build Lambda completes (via SNS notification or shared state)
