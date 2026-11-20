# Email alerts for approvers (Amazon SNS)

In-app alerts work with no setup. Email alerts reach approvers before they sign in. They need one
SNS topic in us-east-1 with each approver's email subscribed.

## 1. Create the topic (encrypted with the AWS managed SNS key)

```bash
aws sns create-topic --region us-east-1 --name procurement-approval-alerts \
  --attributes KmsMasterKeyId=alias/aws/sns
```

Note the `TopicArn` in the output.

## 2. Subscribe each approver

```bash
aws sns subscribe --region us-east-1 --topic-arn <TopicArn> \
  --protocol email --notification-endpoint approver@example.com
```

Each approver receives an "AWS Notification - Subscription Confirmation" email and must click
**Confirm subscription**. Messages are not delivered until they do.

## 3. Start the app with email alerts on

```bash
export APPROVAL_SNS_TOPIC_ARN=<TopicArn>
export APP_URL=https://d1pr6lnlyeiqdc.cloudfront.net/proxy/8501/
.venv/bin/streamlit run app.py
```

The identity running the app needs only `sns:Publish` on that topic ARN.

## What an alert contains

Case ID, requester, item, quantity, needed-by date, the recommended supplier and total, and the
sign-in link. No passwords or tokens. All data in this project is synthetic.

If SNS fails (network, permissions), the request is still saved, approvers still get the in-app
alert, and the error is written to the audit log as `approvers_notified` with an `errors` entry.

## Clean-up after the event

```bash
aws sns delete-topic --region us-east-1 --topic-arn <TopicArn>
```
