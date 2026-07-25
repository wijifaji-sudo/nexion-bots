with open(r'C:\Users\DELL\Documents\anodex\bot\handlers.py', 'r', encoding='utf-8') as f:
    c = f.read()

import re
# Remove parse_mode="markdown" everywhere
c = c.replace(', parse_mode="markdown"', '')
c = c.replace(', parse_mode="Markdown"', '')
c = c.replace(', parse_mode="MarkdownV2"', '')
# Also handle cases where it's on its own line
c = re.sub(r'\s*parse_mode=["\']markdown["\']', '', c)

with open(r'C:\Users\DELL\Documents\anodex\bot\handlers.py', 'w', encoding='utf-8') as f:
    f.write(c)

remaining = c.count('parse_mode=')
print(f'Done - remaining parse_mode: {remaining}')
