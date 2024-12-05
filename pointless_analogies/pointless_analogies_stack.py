from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as apigw_integrations,
    RemovalPolicy,
    Duration,
    aws_ec2 as ec2,
    aws_s3 as s3,
    aws_s3_deployment as s3_deployment,
    aws_s3_notifications as s3n,
    aws_iam as iam,
    aws_dynamodb as dynamodb,
    custom_resources as cr,
)
from constructs import Construct
import json
import os
import shutil

class PointlessAnalogiesStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a bucket to store template HTML files
        html_bucket = s3.Bucket(
            scope = self,
            id = "PointlessAnalogiesHTMLBucket",
            website_index_document = "index.html",
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=False,
                block_public_policy=False,
                ignore_public_acls=False,
                restrict_public_buckets=False
            ),
            removal_policy = RemovalPolicy.DESTROY,
            auto_delete_objects = True
        )
        html_bucket.grant_public_access()

        # Deploy the all HTML files in html_templates to html_bucket
        s3_deployment.BucketDeployment(
            scope = self, 
            id = "PointlessAnalogiesDeployHTMLTemplates",
            destination_bucket = html_bucket,
            sources = [s3_deployment.Source.asset("./html_templates/")]
        )
        
        # Create a function to display the voting page for a given image
        vote_page_initial_function = _lambda.Function(
            scope = self,
            id = "PointlessAnalogiesVotePageInitialFunction",
            function_name = "PointlessAnalogiesVotePageInitialFunction",
            runtime = _lambda.Runtime.PYTHON_3_11,
            handler = "vote_page_functions.vote_page_initial_function",
            code = _lambda.Code.from_asset("lambda/"),
            timeout = Duration.seconds(30)
        )
        html_bucket.grant_read(vote_page_initial_function)
        vote_page_initial_function.add_environment("HTML_BUCKET_NAME", html_bucket.bucket_name)
        vote_page_initial_function.add_environment("HTML_FILE_NAME", "vote_page.html")

        # Create a function to process votes and display the vote count for a given image
        vote_page_button_function = _lambda.Function(
            scope = self,
            id = "PointlessAnalogiesVotePageButtonFunction",
            function_name = "PointlessAnalogiesVotePageButtonFunction",
            runtime = _lambda.Runtime.PYTHON_3_11,
            handler = "vote_page_functions.vote_page_button_function",
            code = _lambda.Code.from_asset("lambda/"),
            timeout = Duration.seconds(15)
        )
        vote_page_button_function.add_environment("HTML_BUCKET_NAME", html_bucket.bucket_name)

        # Create an HTTP API to access the lambda functions
        http_api = apigw.HttpApi(
            scope = self,
            id = "PointlessAnalogiesHTTPApi",
            api_name = "PointlessAnalogiesHTTPApi",
            default_integration = apigw_integrations.HttpLambdaIntegration(
                id = "PointlessAnalogiesAPIGWVotePageInitialIntegration",
                handler = vote_page_initial_function
            )
        )

        # Add a new route to http_api for vote button actions
        http_api.add_routes(
            path = "/vote",
            methods = [apigw.HttpMethod.POST],
            integration = apigw_integrations.HttpLambdaIntegration(
                id = "PointlessAnalogiesAPIGWVotePageButtonIntegration",
                handler = vote_page_button_function
            )
        )
        vote_page_initial_function.add_environment("API_ENDPOINT", http_api.api_endpoint)


        # Add S3 Bucket to stack
        image_bucket = s3.Bucket(
            self,
            "PA_Images",  # Picture bucket ID
            versioned=False,  # Do not allow multiple versions of the same file
            # Turn off blocks for public access. May want to change for final implementation
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=False,
                block_public_policy=False,
                ignore_public_acls=False,
                restrict_public_buckets=False
            ),
            public_read_access=True,  # Pictures are publicly accessible
            removal_policy=RemovalPolicy.DESTROY,  # Delete all pictures when stack is deleted
            auto_delete_objects=True,  # Auto-delete images when stack is deleted
            bucket_name="pointless-analogies-images"  # Picture bucket name
        )

        web_bucket = s3.Bucket(
            self,
            "PA_Web_Content",  # Web content bucket ID
            versioned=False,  # Do not allow multiple versions of the same file
            #Turn off blocks for public access. May want to change for final implementation
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=False,
                block_public_policy=False,
                ignore_public_acls=False,
                restrict_public_buckets=False
            ),
            public_read_access=True,  # Web content is publicly accessible
            removal_policy=RemovalPolicy.DESTROY,  # Delete all web content when stack is deleted
            auto_delete_objects=True,  # Auto-delete images when stack is destroyed
            bucket_name="pointless-analogies-web-content"  # Web content bucket name
        )
        
        # Create a DynamoDB table to store voting data
        table = dynamodb.TableV2(
            scope = self,
            id = "PointlessAnalogiesVotesTable",
            table_name = "PointlessAnalogiesVotesTable",
            partition_key = dynamodb.Attribute(name = "ImageHash", type = dynamodb.AttributeType.STRING),
            removal_policy = RemovalPolicy.DESTROY,
        )

        # Create a lambda function to add an initial image to the database
        initial_image = _lambda.Function(
            scope = self,
            id = "PointlessAnalogiesInitialImage",
            function_name = "PointlessAnalogiesInitialImage",
            runtime = _lambda.Runtime.PYTHON_3_11,
            # Name of the function to be called by the lambda
            handler = "initial_image.initial_image",
            # Specify the file to take the code from
            code = _lambda.Code.from_asset("lambda/"),
            # Increase lambda function timeout to 30 seconds to make sure the database has time to be initialized
            timeout = Duration.seconds(30)
        )

        # Add the name of the table to the initial_image lambda function
        initial_image.add_environment("TABLE_NAME", table.table_name)

        # Allow initial_image to read and write from the table
        table.grant_write_data(initial_image)
        table.grant_read_data(initial_image)

        # Create custom resource provider to manage the custom resource that adds an initial image to the table
        initial_image_provider = cr.Provider(
            scope = self,
            id = "PointlessAnalogiesInitialImageProvider",
            on_event_handler = initial_image
        )

        # Create custom resource to call the lambda function that adds an initial image to the table
        initial_image_resource = cr.AwsCustomResource(
            scope = self,
            id = "PointlessAnalogiesInitialImageResource",
            function_name = "PointlessAnalogiesInitialImageResourceFunction",
            # Define the function to call when the stack is created
            on_create = cr.AwsSdkCall(
                service = "Lambda",
                action = "invoke",
                parameters = {
                    "FunctionName": initial_image.function_name,
                    "InvocationType": "RequestResponse",
                    "Payload": "{}"
                },
                physical_resource_id = cr.PhysicalResourceId.of("PointlessAnalogiesInitialImageResourceID")
            ),
            policy = cr.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions = ["lambda:InvokeFunction"],
                    resources = [initial_image.function_arn]
                )
            ])
        )

        # Add Lambda function that serves as site index
        test_fun = _lambda.Function(
            self,
            "Index",  # Lambda ID
            runtime=_lambda.Runtime.PYTHON_3_11,  # Python version
            handler="index.lambda_handler",  # Name of the method within index.py
            code=_lambda.Code.from_asset("lambda/"),  # Specify source location
            # Increase lambda function timeout to 30 seconds.
            # This is needed since getting the objects from S3 takes more time than
            # the default 25 ms
            timeout=Duration.seconds(30),
            # Add the bucket name to the environment.
            # This is needed as the bucket name that cdk generates is random
            environment={
                "BUCKET_NAME": image_bucket.bucket_name 
            }
        )

        category_role = iam.Role(
            self,
            "CategoryRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole")
            ]
        )

        category_invoke_policy = iam.Policy(
            self,
            "CategoryInvokePolicy",
            statements=[
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
                    resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:get-categories"]
                )
            ]
        )
        category_role.attach_inline_policy(category_invoke_policy)

        categories = _lambda.Function(
            self,
            "Categories",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="categories.lambda_handler",
            code=_lambda.Code.from_asset("lambda/"),
            timeout=Duration.seconds(5),
            function_name="get-categories"
        )

        uploaded_images = _lambda.Function(
            self,
            "Uploaded_images",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="image_handler.lambda_handler",
            code=_lambda.Code.from_asset("lambda/"),
            timeout=Duration.seconds(30),
            role=category_role
        )

        uploaded_images.add_environment("TABLE_NAME", table.table_name)

        table.grant_read_write_data(uploaded_images)

        # Add an API Gateway REST API that serves to call the lambda function.
        # This gives us the URL for the website
        endpoint = apigw.LambdaRestApi(
            self,
            "IndexApiEndpoint",  # ID to associate api within CDK
            handler=test_fun,  # Set handler to be the defined lambda index function
            rest_api_name="IndexApi"  # Name of the API
        )

        # Grant read access for the image bucket to the index lambda
        image_bucket.grant_read(test_fun)
        image_bucket.grant_read_write(uploaded_images)

        image_bucket_notif = s3n.LambdaDestination(uploaded_images)
        image_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            image_bucket_notif
        )

        # Create a policy that gives the ability to list bucket contents of the
        # image bucket
        list_bucket_policy = iam.PolicyStatement(
            actions=["s3:ListBucket"],  # Allowed actions...
            resources=[image_bucket.bucket_arn]  # for this bucket
        )

        # Add the defined policy to the lambda function
        test_fun.role.attach_inline_policy(
            iam.Policy(
                self,
                "ListBucketPolicy",  # Policy ID
                statements=[list_bucket_policy]  # Add permissions
            )
        )