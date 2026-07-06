import os
import re

def scan_routes(base_dir="D:/SourceCode/Web/Python/trading-system-upgrade"):
    routes = []
    pattern = re.compile(r'@.*route\(["\'](.*?)["\']')
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".py"):
                with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                    content = f.read()
                    matches = pattern.findall(content)
                    routes.extend(matches)
    return sorted(set(routes))

if __name__ == "__main__":
    routes = scan_routes()
    print("後端路由清單:")
    for r in routes:
        print(r)
