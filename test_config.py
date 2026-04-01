import os
from dotenv import load_dotenv

os.chdir(r"c:\Users\dhruv\Downloads\AWS")
load_dotenv()

import config
print(f"DEMO_MODE in config: {getattr(config, 'DEMO_MODE', 'MISSING')}")

try:
    from aws.ec2_manager import deploy_server
    print("deploy_server imported successfully")
except Exception as e:
    print(f"Error importing deploy_server: {e}")

try:
    from app import aws_deploy_server
    print(f"aws_deploy_server is: {aws_deploy_server}")
    
    from app import app
    with app.app_context():
        print(f"Flask sees config.DEMO_MODE as: {getattr(config, 'DEMO_MODE', True)}")
except Exception as e:
    print(f"Error importing from app: {e}")
