# Security

If private data survives cleaning, or a crafted file can crash or hang the tool, please report it through GitHub's **private vulnerability reporting** (Security tab > Report a vulnerability) rather than a public issue.

Design choices: no dependencies, no network access in the command line tool, a Content-Security-Policy that blocks all network requests in the web page, original files are never modified unless `--in-place` is given, and output is written atomically.
