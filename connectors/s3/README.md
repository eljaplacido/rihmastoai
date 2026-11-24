# The S3-compatible storage connector (read-only)

How Rihmasto itself reads one bucket of S3-compatible object storage through Gnomon (D-0015): AWS S3,
MinIO, Ceph, Cloudflare R2 or any store that takes AWS Signature Version 4 with path-style addressing.
It ships its own narrow server, `server.py` (standard library only), which lists keys and reads object
metadata and text, and never writes. For a product that keeps files in cloud storage, see
[docs/guides/data-integrations.md](../../docs/guides/data-integrations.md).

| File | What it is |
|---|---|
| `connector.json` | The connector: `python server.py`, pinned by its sha256, three read tools, the write tools never allowed, and the endpoint, region, bucket and keys by reference. |
| `server.py` | The narrow MCP server over stdio: `list_objects`, `get_object_metadata` and `get_object_text` (at most 64 KiB), signed with SigV4, GET and HEAD only, one bucket, https (http on loopback only). |
| `mapping.py` | Pure functions: each object becomes a note (`s3:reports/daily/2026-11-22.csv`), its text quoted as untrusted data. |
| `fake.py` | An S3-compatible store on 127.0.0.1 for the contract suite: it answers only a request with a valid signature, and refuses and records any write. |
| `fixtures/` | The pinned tools/list, a rug pull that adds `put_object`, injection samples and the fake's objects. |

## Setup

1. Create credentials that can only read the one bucket (an IAM policy with `s3:ListBucket` and
   `s3:GetObject` on it, or the store's equivalent). The server never writes; the policy makes sure.
2. Name the endpoint, region and bucket in the variables the credentials reference, and keep the secret
   key in the operating system's store (`os:RIHMA_S3_SECRET_ACCESS_KEY`).
3. `rihmasto connector validate s3`, then `python -m unittest tests.test_connectors_contract`: the suite
   runs `server.py` against the fake store, signed, and shows that no write reaches it.
4. IT enables it (`rihmasto connector enable s3 --person <name> --persona it`) and decides its card. After
   `server.py` changes, `server.pin.sha256` must pin its new sha256, or it may not run.

Azure Blob Storage and Google Cloud Storage have their own APIs; their connectors are planned. GCS's
XML API takes HMAC keys with SigV4 and may work with this one (UNVERIFIED).
