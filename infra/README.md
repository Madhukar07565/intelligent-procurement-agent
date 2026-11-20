# Team test environment (AWS CDK, Python)

One shared, HTTPS copy of the Procurement Agent so teammates can test it without access to the
development workspace.

```
Teammates ──HTTPS──> CloudFront (*.cloudfront.net)
                        │  adds secret X-Origin-Verify header
                        ▼
                     ALB  (accepts CloudFront address ranges only; 403 without the header)
                        ▼
                     ECS Fargate, 1 task (Streamlit app, 0.5 vCPU / 1 GB)
                        ├── Amazon Bedrock: Nova Lite only (task role)
                        └── logins: password hashes from Secrets Manager
```

Why not App Runner: Streamlit needs WebSockets, which App Runner does not support, and App Runner
closed to new customers on 30 April 2026.

## Limits of this environment (by design, for testing)

- **Data resets** when the task restarts or is redeployed. Cases, alerts and POs are stored inside
  the single task (SQLite). Moving them to DynamoDB is phase 1 of `docs/architecture/agentcore-design.md`.
- **One task only.** Two tasks would each have their own data and their own Bedrock rate limiter.
- **Logins are app accounts, not Cognito.** Each teammate has a requester login (their email) and an
  approver login (email with `+approver`). Because they are separate accounts, a teammate *can*
  approve their own request in this environment. Fine for testing; not for real use.
- HTTPS uses the default CloudFront certificate. No custom domain.

## Deploy

```bash
cd /workshop/infra
python3.11 -m venv .venv && .venv/bin/pip install aws-cdk-lib constructs
/workshop/procurement_agent/.venv/bin/python scripts/team_users.py   # logins + origin secret in .deploy/
# upload .deploy/users.json to Secrets Manager secret procurement-agent/test/users (create or put value)
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/us-east-1 -c originSecret=$(cat .deploy/origin-secret)   # once
cdk diff   -c originSecret=$(cat .deploy/origin-secret)
cdk deploy -c originSecret=$(cat .deploy/origin-secret) --outputs-file .deploy/outputs.json
```

The app link is the `AppUrl` output.

## Change logins

```bash
/workshop/procurement_agent/.venv/bin/python scripts/team_users.py --reset   # new passwords
# put .deploy/users.json into the secret again, then restart the task:
aws ecs update-service --cluster <ClusterName> --service <ServiceName> --force-new-deployment --region us-east-1
```

To add a person, edit `TEAM` in `scripts/team_users.py`.

## Logs

CloudWatch log group in the `LogGroup` output (kept 1 week).

## Cost (us-east-1, approximate)

The ALB is about USD 0.6 a day and the Fargate task about USD 0.5 a day. CloudFront, Bedrock and
Secrets Manager add cents at test volume. In total that is roughly USD 1–1.5 a day while deployed.

## Remove after the event

```bash
cdk destroy -c originSecret=$(cat .deploy/origin-secret)
aws secretsmanager delete-secret --secret-id procurement-agent/test/users --force-delete-without-recovery --region us-east-1
# optional: delete the CDKToolkit stack, after emptying its S3 bucket and ECR repository
```

`.deploy/` holds the passwords and secrets. It is git-ignored and owner-only. Delete it when done.
