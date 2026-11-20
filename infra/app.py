#!/usr/bin/env python3
"""Shared team test environment for the Intelligent Procurement Agent.

  Teammates -> CloudFront (HTTPS, *.cloudfront.net) -> ALB (CloudFront only + secret header)
            -> 1 ECS Fargate task (Streamlit app) -> Amazon Bedrock (Nova Lite)

Deploy (see README.md in this folder):
  .venv/bin/python scripts/team_users.py            # creates logins, stores hashes in Secrets Manager
  cdk deploy -c originSecret=$(cat .deploy/origin-secret)
"""
import os

import aws_cdk as cdk
from aws_cdk import (Duration, RemovalPolicy, Stack, Tags, aws_cloudfront as cloudfront,
                     aws_cloudfront_origins as origins, aws_ec2 as ec2, aws_ecr_assets as ecr_assets,
                     aws_ecs as ecs, aws_elasticloadbalancingv2 as elbv2, aws_iam as iam, aws_logs as logs,
                     aws_secretsmanager as secretsmanager)
from constructs import Construct

REGION = "us-east-1"
APP_PORT = 8501
MODEL_PROFILE = "us.amazon.nova-lite-v1:0"
# Regions the us.* Nova Lite inference profile can route to (checked with GetInferenceProfile).
MODEL_REGIONS = ["us-east-1", "us-east-2", "us-west-2"]
USERS_SECRET_NAME = "procurement-agent/test/users"
CLOUDFRONT_ORIGIN_PREFIX_LIST = "pl-3b927c52"  # com.amazonaws.global.cloudfront.origin-facing, us-east-1
ORIGIN_HEADER = "X-Origin-Verify"
APP_DIR = os.path.join(os.path.dirname(__file__), "..", "procurement_agent")


class ProcurementAgentTestStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, origin_secret: str, **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)

        # Default VPC, public subnets in three AZs: no NAT gateway cost.
        vpc = ec2.Vpc.from_lookup(self, "Vpc", is_default=True)
        subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC,
                                      availability_zones=["us-east-1a", "us-east-1b", "us-east-1c"])

        alb_sg = ec2.SecurityGroup(self, "AlbSg", vpc=vpc, allow_all_outbound=False,
                                   description="ALB: HTTP from CloudFront origin-facing addresses only")
        alb_sg.add_ingress_rule(ec2.Peer.prefix_list(CLOUDFRONT_ORIGIN_PREFIX_LIST), ec2.Port.tcp(80),
                                "CloudFront origin-facing")
        app_sg = ec2.SecurityGroup(self, "AppSg", vpc=vpc, allow_all_outbound=True,
                                   description="App task: port 8501 from the ALB only; outbound HTTPS to AWS APIs")
        app_sg.add_ingress_rule(alb_sg, ec2.Port.tcp(APP_PORT), "From ALB")
        alb_sg.add_egress_rule(app_sg, ec2.Port.tcp(APP_PORT), "To app task")

        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        log_group = logs.LogGroup(self, "AppLogs", retention=logs.RetentionDays.ONE_WEEK,
                                  removal_policy=RemovalPolicy.DESTROY)

        task = ecs.FargateTaskDefinition(self, "Task", cpu=512, memory_limit_mib=1024,
                                         runtime_platform=ecs.RuntimePlatform(
                                             cpu_architecture=ecs.CpuArchitecture.X86_64,
                                             operating_system_family=ecs.OperatingSystemFamily.LINUX))
        # Least privilege: invoke only the Nova Lite inference profile and the models it routes to.
        task.task_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[f"arn:aws:bedrock:{REGION}:{self.account}:inference-profile/{MODEL_PROFILE}"]
                      + [f"arn:aws:bedrock:{r}::foundation-model/amazon.nova-lite-v1:0" for r in MODEL_REGIONS],
        ))

        users_secret = secretsmanager.Secret.from_secret_name_v2(self, "UsersSecret", USERS_SECRET_NAME)
        image = ecr_assets.DockerImageAsset(self, "AppImage", directory=APP_DIR,
                                            platform=ecr_assets.Platform.LINUX_AMD64)
        task.add_container(
            "app",
            image=ecs.ContainerImage.from_docker_image_asset(image),
            port_mappings=[ecs.PortMapping(container_port=APP_PORT)],
            environment={
                "AWS_REGION": REGION,
                "AWS_DEFAULT_REGION": REGION,
                "BEDROCK_MODEL_ID": MODEL_PROFILE,
                "ALERT_POLL_SECONDS": "15",
            },
            secrets={"USERS_JSON": ecs.Secret.from_secrets_manager(users_secret)},
            logging=ecs.LogDrivers.aws_logs(stream_prefix="app", log_group=log_group),
            readonly_root_filesystem=False,  # the app writes SQLite, audit and PO files under /app/data
        )

        # Exactly one task: cases live in SQLite inside the task, and the Bedrock rate limit is per process.
        service = ecs.FargateService(
            self, "Service", cluster=cluster, task_definition=task, desired_count=1,
            min_healthy_percent=0, max_healthy_percent=100, assign_public_ip=True,
            vpc_subnets=subnets, security_groups=[app_sg],
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )

        alb = elbv2.ApplicationLoadBalancer(self, "Alb", vpc=vpc, internet_facing=True, vpc_subnets=subnets,
                                            security_group=alb_sg, idle_timeout=Duration.minutes(30),
                                            drop_invalid_header_fields=True)
        listener = alb.add_listener("Http", port=80, open=False,
                                    default_action=elbv2.ListenerAction.fixed_response(
                                        403, content_type="text/plain", message_body="Forbidden"))
        listener.add_targets(
            "App", priority=1, port=APP_PORT, protocol=elbv2.ApplicationProtocol.HTTP, targets=[service],
            conditions=[elbv2.ListenerCondition.http_header(ORIGIN_HEADER, [origin_secret])],
            health_check=elbv2.HealthCheck(path="/_stcore/health", healthy_http_codes="200",
                                           interval=Duration.seconds(30)),
            deregistration_delay=Duration.seconds(15),
            stickiness_cookie_duration=Duration.hours(8),
        )

        distribution = cloudfront.Distribution(
            self, "Cdn",
            comment="Procurement Agent team test environment",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    alb, protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    custom_headers={ORIGIN_HEADER: origin_secret},
                    read_timeout=Duration.seconds(60), keepalive_timeout=Duration.seconds(60)),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,  # WebSocket upgrade, cookies
            ),
        )

        cdk.CfnOutput(self, "AppUrl", value=f"https://{distribution.distribution_domain_name}/",
                      description="Share this link with the team")
        cdk.CfnOutput(self, "LogGroup", value=log_group.log_group_name)
        cdk.CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        cdk.CfnOutput(self, "ServiceName", value=service.service_name)


app = cdk.App()
origin_secret = app.node.try_get_context("originSecret")
if not origin_secret or len(origin_secret) < 32:
    raise SystemExit("Pass the CloudFront origin secret: cdk ... -c originSecret=$(cat .deploy/origin-secret)")
stack = ProcurementAgentTestStack(app, "ProcurementAgentTest", origin_secret=origin_secret,
                                  env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=REGION),
                                  description="Procurement Agent shared team test environment (hackathon)")
Tags.of(stack).add("project", "procurement-agent")
Tags.of(stack).add("environment", "team-test")
app.synth()
