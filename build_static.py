import os
from app import app
from flask import url_for

def build():
    frontend_dir = os.path.join(os.path.dirname(__file__), 'frontend')
    os.makedirs(frontend_dir, exist_ok=True)
    
    # We need a request context to use url_for and render_template
    with app.test_request_context('/'):
        # Override url_for to return relative paths for static files
        app.jinja_env.globals['url_for'] = lambda endpoint, **values: (
            f"./{values['filename']}" if endpoint == 'static' else f"{endpoint}.html" if endpoint != 'index' else "index.html"
        )
        
        # The endpoints and their target filenames
        pages = {
            'landing': 'landing.html',
            'index': 'index.html',
            'servers_page': 'servers_page.html',
            'compare_page': 'compare_page.html',
            'history_page': 'history_page.html'
        }
        
        from flask import render_template
        
        for endpoint, filename in pages.items():
            try:
                # The actual template name might be different from the endpoint
                if endpoint == 'servers_page':
                    template = 'servers.html'
                elif endpoint == 'compare_page':
                    template = 'compare.html'
                elif endpoint == 'history_page':
                    template = 'history.html'
                elif endpoint == 'index':
                    template = 'index.html'
                elif endpoint == 'landing':
                    template = 'landing.html'
                else:
                    template = f"{endpoint}.html"
                
                print(f"Rendering {template} -> {filename}")
                html = render_template(template)
                
                # Write to frontend dir
                out_path = os.path.join(frontend_dir, filename)
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(html)
                    
            except Exception as e:
                print(f"Error rendering {endpoint}: {e}")

if __name__ == '__main__':
    build()
    print("Static build complete.")
