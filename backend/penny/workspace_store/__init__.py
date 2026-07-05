"""RLS-scoped, versioned blob-workspace store.

A general mechanism for per-tenant, versioned file storage with a filesystem
checkout: opaque capability tokens broker access to content-addressed blobs,
and a manifest/head chain gives atomic, lost-update-safe versioning. Nothing
here is finance- or Penny-specific — the store speaks only in prefixes,
manifests, byte blobs, and a checkout directory of arbitrary files (see the
plan's Modularization note: this is the portable core; the memory/reports
consumers live outside it).
"""
