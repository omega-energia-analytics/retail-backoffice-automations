import os
import sys
import webview

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api import Api

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(base_dir, 'ui', 'index.html')

    api = Api()
    window = webview.create_window(
        'Monitor NFF — Serena',
        html_path,
        js_api=api,
        width=1400,
        height=900,
        min_size=(1100, 700),
        background_color='#1A1A1A'
    )
    api.set_window(window)
    webview.start(debug=False)

if __name__ == '__main__':
    main()