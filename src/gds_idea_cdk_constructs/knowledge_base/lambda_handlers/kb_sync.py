"""SQS-triggered Lambda handler for Bedrock Knowledge Base sync.

Invoked by an SQS queue that receives S3 event notifications.  The queue
is configured with a batching window (default 20 minutes) so that many
S3 object events are collected into a single Lambda invocation.  This
handler then fires **one** ``StartIngestionJob`` call regardless of how
many files changed, avoiding API throttling.

Environment variables:
    KNOWLEDGE_BASE_ID: Bedrock Knowledge Base ID.
    DATA_SOURCE_ID: Bedrock Data Source ID.
"""

import os

import boto3

KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID", "")
DATA_SOURCE_ID = os.environ.get("DATA_SOURCE_ID", "")


def handler(event, context):
    """Start a Bedrock KB ingestion job.

    The SQS batch may contain many S3 event records — we intentionally
    ignore the individual records and trigger a full data-source sync.
    Bedrock handles incremental ingestion internally (only new/changed
    files are re-embedded).
    """
    if not KNOWLEDGE_BASE_ID or not DATA_SOURCE_ID:
        print(
            "ERROR: KNOWLEDGE_BASE_ID and DATA_SOURCE_ID must be set. "
            f"KNOWLEDGE_BASE_ID={KNOWLEDGE_BASE_ID!r}, "
            f"DATA_SOURCE_ID={DATA_SOURCE_ID!r}"
        )
        return {"statusCode": 400, "body": "Missing environment variables"}

    client = boto3.client("bedrock-agent")

    num_records = len(event.get("Records", []))
    print(
        f"Starting ingestion job for KB={KNOWLEDGE_BASE_ID}, "
        f"DataSource={DATA_SOURCE_ID} "
        f"(triggered by {num_records} SQS message(s))"
    )

    try:
        response = client.start_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            dataSourceId=DATA_SOURCE_ID,
        )
        ingestion_job = response.get("ingestionJob", {})
        job_id = ingestion_job.get("ingestionJobId", "unknown")
        status = ingestion_job.get("status", "unknown")
        print(f"Ingestion job started: jobId={job_id}, status={status}")

        return {"statusCode": 200, "body": f"Ingestion job {job_id} started"}

    except Exception as e:
        # Log but do NOT re-raise — a raised exception causes SQS to retry,
        # which would start duplicate ingestion jobs.
        print(f"ERROR starting ingestion job: {e}")
        return {"statusCode": 500, "body": str(e)}
