import os
import sys

# Change to the application directory
os.chdir(r"c:\Users\dhruv\Downloads\AWS")

import config
import boto3

print("\n--- TERMINAL VERIFICATION ---")
try:
    # 1. Verify STS Identity
    print("\n1. Checking AWS Login (STS)...")
    sts = boto3.client(
        "sts",
        region_name=config.AWS_DEFAULT_REGION,
        aws_access_key_id=config.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
    )
    identity = sts.get_caller_identity()
    print("✅ SUCCESS! Connected to AWS!")
    print(f"   Account ID: {identity['Account']}")
    print(f"   User ARN:   {identity['Arn']}")
    
    # 2. Check EC2 instances
    print("\n2. Finding deployed LoadFlow servers in EC2...")
    ec2 = boto3.resource(
        "ec2",
        region_name=config.AWS_DEFAULT_REGION,
        aws_access_key_id=config.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
    )
    
    instances_found = 0
    # Look for instances with the 'Name' tag containing 'lb-server'
    instances = ec2.instances.filter(
        Filters=[{"Name": "tag:Name", "Values": ["*lb-server*"]}]
    )
    
    print("\n--- Servers found in your AWS Account ---")
    for inst in instances:
        instances_found += 1
        name = "Unknown"
        for t in inst.tags or []:
            if t['Key'] == 'Name':
                name = t['Value']
        
        print(f"✅ Server: {name:15} | ID: {inst.id:20} | State: {inst.state['Name']:10} | Type: {inst.instance_type}")
        
    if instances_found == 0:
        print("   No loadflow servers found yet. Go to the browser and click 'Deploy Server'!")

    print("\nTerminal verification complete!")
except Exception as e:
    print("❌ FAILED to connect to AWS:")
    print(e)
