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
- **Memory usage**: Each cached file consumes Lambda memory. Bounded by `maxsize` (default 128 files).

### Mitigations

- Sites that rebuild frequently (hourly or less) naturally have short staleness windows
- Lambda environments under low traffic recycle quickly
- `CACHE_MAX_SIZE` can be reduced for memory-constrained deployments
- A future enhancement could clear the cache when the build Lambda completes (via SNS notification or shared state)

## Update: 404s are not cached

**Discovered during testing (first real deployment):** caching negative results (missing files) caused a genuinely broken experience, not just a theoretical risk. Sequence observed:

1. A request hit the serve Lambda while the site's first build was still in progress (S3 empty) — `index.html` → `NoSuchKey` → cached as `None`
2. The build completed successfully and uploaded all files to S3
3. A subsequent request hit the *same warm Lambda execution environment* — the cached `None` for `index.html` was returned, producing a 404 even though the file now existed in S3
4. This persisted until the Lambda environment happened to recycle, with no way to force it

This is worse than the "stale content" case (Consequence 1 above) because it's not just serving *old* content — it's actively refusing to serve content that exists, with no user-facing indication of when it will resolve itself.

**Fix applied:** split the cached function so that only successful S3 reads are memoized. Missing objects and errors raise an internal exception (`_NotFoundError`) instead of returning `None`. `functools.lru_cache` does not cache raised exceptions — only return values — so a call that raises is always re-executed on the next request. This preserves all the positive consequences above (successful reads are still cached) while removing the negative-caching failure mode entirely.

```python
def _get_s3_content(bucket, key):
    try:
        return _get_s3_content_cached(bucket, key)
    except _NotFoundError:
        return None


@lru_cache(maxsize=CACHE_MAX_SIZE)
def _get_s3_content_cached(bucket, key):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        raise _NotFoundError() from None
    ...
```

The only remaining staleness case is genuinely-changed *existing* files (an already-cached successful read becoming outdated after a rebuild) — this is the originally accepted trade-off and remains unchanged.
