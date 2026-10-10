"""Publish site/ to the gh-pages branch with plain git (no copying, works with 50,000+ files).

Commits the contents of site/ as a new gh-pages commit using a temporary index and site/ as the
work tree, then pushes it. Build site/ first: python tools/make_site.py [--preset ...]
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(HERE, "site")
INDEX = os.path.join(HERE, "cache", "gh-pages.index")

def git(*args, env=None):
    return subprocess.run(["git", *args], cwd=HERE, env=env, check=True, capture_output=True, text=True).stdout.strip()

if not os.path.exists(os.path.join(SITE, "index.html")):
    sys.exit("site/ is missing: run python tools/make_site.py first")
os.makedirs(os.path.dirname(INDEX), exist_ok=True)
if os.path.exists(INDEX):
    os.remove(INDEX)
env = {**os.environ, "GIT_INDEX_FILE": INDEX, "GIT_WORK_TREE": SITE}
git("add", "-A", ".", env=env)
tree = git("write-tree", env=env)
subprocess.run(["git", "fetch", "-q", "origin", "gh-pages"], cwd=HERE)  # fine if the branch doesn't exist yet
try:
    parent = ["-p", git("rev-parse", "origin/gh-pages")]
except subprocess.CalledProcessError:
    parent = []
msg = "Deploy site from " + git("rev-parse", "--short", "HEAD")
commit = git("commit-tree", tree, *parent, "-m", msg)
git("push", "origin", f"{commit}:refs/heads/gh-pages")
os.remove(INDEX)
print(f"pushed {commit[:7]} to gh-pages ({msg})")
