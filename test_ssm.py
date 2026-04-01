import os
os.chdir(r"c:\Users\dhruv\Downloads\AWS")
import config
from aws.ec2_manager import _get_latest_amazon_linux2_ami
import traceback

print("Testing SSM Parameter Store access...")
try:
    ami = _get_latest_amazon_linux2_ami("us-east-1", config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    print("Returned AMI in ec2_manager:", ami)
except Exception as e:
    print("Error calling function:", e)

print("\nRunning directly with boto3:")
try:
    import boto3
    ssm = boto3.client(
        "ssm",
        region_name="us-east-1",
        aws_access_key_id=config.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
    )
    print("Getting parameter...")
    resp = ssm.get_parameter(Name="/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2")
    print("Success:", resp["Parameter"]["Value"])
except Exception as e:
    print("BOTO3 EXCEPTION:")
    traceback.print_exc()
