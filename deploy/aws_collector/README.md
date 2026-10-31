# AWS full-snapshot collector

> Free-plan deployment hold: the account holder reports that CloudShell requires a Paid plan. They require keeping the AWS Free account plan with no paid-plan upgrade or out-of-pocket charges. Do not run the deployment/create/start commands below until all required services are confirmed available under this account plan. AWS CLI on the local computer can replace CloudShell only if those backend services are allowed; it does not bypass account-plan restrictions. No cloud resources have been created. Standard-rate cost estimates below describe resource consumption, not permission to incur a bill.


**ABANDONED for this account; do not run the AWS deploy/start instructions below.** Original code is retained as inactive implementation evidence. The Windows task remains active until cloud handoff is verified. No AWS credentials are stored here.

## Resources and cost

One private encrypted S3 bucket, one Python 3.14 Lambda (512 MB, timeout 90 seconds), two scoped IAM execution roles, a 14-day log group, and EventBridge Scheduler every two minutes. No EC2, VPC/NAT gateway, public bucket, function URL or API endpoint. Data bucket deletion/replacement policy is **Retain**. The schedule is initially **DISABLED** and ends at **2026-12-13 07:59 UTC**.

At 720 polls/day, assume 21,600 monthly invocations, <=10 seconds average at 512 MB, <=7 S3 writes/poll and roughly 1–2 GB compressed new data/month. The resulting estimate is **about USD 1–3/month** in us-east-1 at standard rates; shared free allowances/credits can lower it. This is an estimate, not a hard budget cap. Existing account usage, region, failures and response sizes change cost. Retained S3 storage remains billable after collection stops. No paid provisioned concurrency or reserved concurrency quota allocation is requested.

References checked 2026-10-30: [Lambda pricing](https://aws.amazon.com/lambda/pricing/), [S3 pricing](https://aws.amazon.com/s3/pricing/), [Scheduler pricing](https://aws.amazon.com/eventbridge/pricing/). Lambda and Scheduler have shared free allowances; raw S3 storage/operations must not be assumed free. Optional AWS Budget alerts must be configured in your own account and do not enforce a spending cap.

## Deploy from your browser

Use [AWS CloudShell in us-east-1](https://us-east-1.console.aws.amazon.com/cloudshell/home?region=us-east-1). It uses your console login; do not send access keys/passwords to the chat. Your identity needs permission to create the stack resources and pass the scoped roles. An AWS Academy/organization account may restrict IAM, Scheduler or Lambda creation; stop on a permission error rather than using someone else's credentials.

1. Upload the generated **bikeflow-aws-collector.zip** using CloudShell Actions > Upload file. It contains only deployment code/template/docs, no raw data or credentials. The bundle is generated locally outside the repo; see the project handoff notes for its path.
2. Run:

```bash
unzip -n bikeflow-aws-collector.zip -d bikeflow-aws-collector
cd bikeflow-aws-collector
python3 manage_collector.py plan
```

3. After reviewing the displayed resources and estimated cost, create the stack. This creates billable resources and scoped IAM roles, but leaves the scheduler disabled:

```bash
python3 manage_collector.py deploy --confirm-create-resources
```

The first stack creation can take a few minutes. The script validates the template with AWS and never silently replaces an existing stack of the same name. A rollback with a retained bucket can leave a small private bucket to review in the console; it is never silently emptied.

4. Smoke-test the function and persisted S3 manifest, then enable the schedule:

```bash
python3 manage_collector.py start
```

5. After 2–4 minutes, verify at least two distinct recent **scheduled** polls, a private bucket, and stored snapshot hashes:

```bash
python3 manage_collector.py verify
```

This writes `cloud_handoff_evidence.json`. Only after it passes should the Windows task be disabled. The evidence records that the local task has not yet been disabled. Once the cloud scheduler is enabled, closing CloudShell or shutting down your laptop does not stop the AWS services.

```powershell
Disable-ScheduledTask -TaskName 'BikeFlowAI-Divvy-Full-GBFS-Collector'
```

Keep the existing local data. Do not merge/delete local/cloud snapshots blindly; provenance distinguishes their collectors and time ranges. The original local collector script and historical training protocol are unchanged.

## Monitor, stop and download

```bash
python3 manage_collector.py status
python3 manage_collector.py stop
```

`stop` disables scheduling through a CloudFormation update; it preserves raw data and source evidence. The configured end also stops future schedule invocations and capture code enforces the same cutoff. No automatic raw-data expiry/deletion is installed.

Read `DataBucketName` from status/stack outputs, then download privately using authenticated AWS CLI to a new external data folder:

```bash
aws s3 sync s3://YOUR_BUCKET/current_validation/ ./aws-current-validation/
```

For Windows use a destination under `Documents/BikeFlowAI-data/divvy/aws_validation/`, outside the project. CloudShell is for deployment/verification, not a long-running collector process or large-data storage.

## Semantics and reliability

Each invocation starts fresh, follows official HTTPS discovery, fetches station metadata before full status, and retains unchanged counts. Immutable S3 metadata versions are content-deduplicated; each manifest records actual stored hashes and this poll's captured hash if different. Polls have immutable `polls/YYYY/MM/DD/<slot>.json` manifests instead of shared `polls.jsonl` or `state.json`. Publish a successful manifest only after referenced raw objects upload.

Conditional S3 slot claims prevent duplicate scheduled captures without shared mutable counters or account reserved-concurrency requirements. Failed/incomplete claims are visible as missing/error manifests; they are not backfilled into an invented historical state. Network/storage failures raise Lambda errors and are logged. A storage outage can prevent its error manifest, so CloudWatch errors and expected-slot missingness must also be checked.

Scheduler has [60-second delivery precision](https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html), even with flexible windows OFF. This is a nominal two-minute cadence, not exact-second sampling. Requests queued more than 90 seconds from their scheduled time are excluded with an error record. Retries are disabled to avoid delayed historical backfill; a fresh later slot runs independently. The actual request/receipt/provider times remain authoritative.

AWS includes the Python SDK in the managed runtime; its version can change. No external scientific packages or new credentials are bundled. `source_manifest.json` hashes original collector bytes, adapter, inline code and template. Rebuild the template after changing either collector or adapter:

```powershell
.\.venv\Scripts\python.exe deploy/aws_collector/build_template.py
```

This deployment does not broaden data redistribution rights. Raw objects remain private under the source-specific terms documented in [DATA_SOURCES.md](../../DATA_SOURCES.md).

## Current migration decision

AWS migration is **abandoned for this account**: its account eligibility flow requires a Paid plan, and no paid upgrade or out-of-pocket charges are authorized. No AWS resources were created. The proposed no-billing-account replacement is [Google Apps Script + private Drive](../apps_script/README.md), using a nominal five-minute cloud trigger. That replacement is prepared only, not deployed. The Windows collector remains active until two real Google scheduled runs are verified.
