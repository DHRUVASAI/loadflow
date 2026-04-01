import os
os.chdir(r"c:\Users\dhruv\Downloads\AWS")
import traceback
import config

print("DEMO_MODE:", getattr(config, "DEMO_MODE", True))

try:
    from aws.ec2_manager import deploy_server
    print("Function imported.")
    
    server = deploy_server()
    print("Returned server:", server)
except Exception as e:
    print("Exception:")
    traceback.print_exc()

