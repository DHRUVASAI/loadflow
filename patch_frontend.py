import os
import re

frontend_dir = os.path.join(os.path.dirname(__file__), 'frontend')

API_GLOBAL = """
<script>
  // Point this to your Hugging Face Space backend URL once deployed
  // Format: "https://<hf_username>-<space_name>.hf.space"
  // Example: "https://agentvds007-loadflow.hf.space"
  const API_BASE_URL = "https://agentvds007-loadflow.hf.space"; 
</script>
</head>
"""

for filename in os.listdir(frontend_dir):
    if filename.endswith('.html'):
        filepath = os.path.join(frontend_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 1. Strip the old API_BASE_URL if it exists
        content = re.sub(
            r'<script>\s*// Point this to your.*?const API_BASE_URL = ".*?";\s*</script>\s*</head>', 
            '</head>', 
            content, 
            flags=re.DOTALL
        )
        
        # 2. Inject API_BASE_URL before </head>
        content = content.replace("</head>", API_GLOBAL)
        
        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

print("Frontend URLs patched for Hugging Face Spaces API.", flush=True)
