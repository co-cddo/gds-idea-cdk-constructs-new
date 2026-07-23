"""
Lambda handler to clean up ACM DNS validation records before hosted zone deletion.

This prevents CloudFormation stack deletion failures when both a certificate
and its validation hosted zone are deleted together.
"""

import time

import boto3

r53 = boto3.client("route53")


def handler(event, context):
    """Clean up ACM validation CNAME records on stack deletion."""
    print(f"Event received: {event}")
    print(f"Request Type: {event.get('RequestType')}")

    try:
        if event.get("RequestType") == "Delete":
            zone_id = event["ResourceProperties"].get("ZoneId")
            domain = event["ResourceProperties"].get("DomainName")

            if not zone_id or not domain:
                print("WARNING: Missing ZoneId or DomainName, skipping cleanup")
                return {"PhysicalResourceId": "AcmDnsCleanup"}

            print(f"Starting ACM DNS cleanup for zone: {zone_id}, domain: {domain}")

            # Give ACM a moment to start its cleanup
            time.sleep(3)

            domain_normalized = domain.rstrip(".")
            deleted_count = 0
            failed_count = 0

            try:
                paginator = r53.get_paginator("list_resource_record_sets")
                for page in paginator.paginate(HostedZoneId=zone_id):
                    for rec in page.get("ResourceRecordSets", []):
                        name = rec.get("Name", "").rstrip(".")
                        rec_type = rec.get("Type", "")

                        # Target ACM validation records: _<hash>.<domain> CNAME
                        if (
                            rec_type == "CNAME"
                            and name.startswith("_")
                            and name.endswith(domain_normalized)
                        ):
                            try:
                                r53.change_resource_record_sets(
                                    HostedZoneId=zone_id,
                                    ChangeBatch={
                                        "Changes": [
                                            {
                                                "Action": "DELETE",
                                                "ResourceRecordSet": rec,
                                            }
                                        ]
                                    },
                                )
                                deleted_count += 1
                                print(f"✓ Successfully deleted record: {name}")
                            except Exception as e:
                                failed_count += 1
                                print(f"⚠ Failed to delete record {name}: {e}")

            except r53.exceptions.NoSuchHostedZone:
                print(f"Hosted zone {zone_id} already deleted - nothing to clean up")
            except Exception as e:
                print(f"ERROR listing records in zone {zone_id}: {e}")

            print(f"Cleanup complete: {deleted_count} deleted, {failed_count} failed")
        else:
            print(f"Skipping cleanup for request type: {event.get('RequestType')}")

        return {"PhysicalResourceId": "AcmDnsCleanup"}

    except Exception as e:
        print(f"CRITICAL: Unhandled error in AcmDnsCleanup: {e}")
        # Never raise - allow stack deletion to continue
        return {"PhysicalResourceId": "AcmDnsCleanup"}
