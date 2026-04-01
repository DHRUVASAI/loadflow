import os
import re

frontend_dir = os.path.join(os.path.dirname(__file__), 'frontend')

API_GLOBAL = """
<script>
  // Point this to your Render.com backend URL once deployed
  // e.g. "https://loadflow-api.onrender.com"
  const API_BASE_URL = "https://loadflow.onrender.com"; 
</script>
</head>
"""

for filename in os.listdir(frontend_dir):
    if filename.endswith('.html'):
        filepath = os.path.join(frontend_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 1. Inject API_BASE_URL before </head>
        content = content.replace("</head>", API_GLOBAL)
        
        # 2. Replace static fetch calls
        # Replace `fetch('/api/` with `fetch(API_BASE_URL + '/api/`
        content = re.sub(r"fetch\(['\"]/api/", r"fetch(API_BASE_URL + '/api/", content)
        
        # Also fix window.location.href for export CSV
        content = content.replace("window.location.href = '/api/export-csv'", "window.location.href = API_BASE_URL + '/api/export-csv'")
        
        # Fix dynamic template urls (if any didn't get caught by the build script override)
        content = content.replace("index.html", "index.html")
        content = content.replace("servers_page.html", "servers_page.html")
        content = content.replace("compare_page.html", "compare_page.html")
        content = content.replace("history_page.html", "history.html") # The actual filename built in frontend is history_page.html, but let's check what the script did.
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

print("Frontend URLs patched for decoupled API.", flush=True)
