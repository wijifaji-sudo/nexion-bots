import re

with open(r'C:\Users\DELL\Documents\anodex\bot\handlers.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix double comma from parse_mode removal
content = content.replace(',,', ',')

# Fix trailing comma before closing paren on same line - "text...",,)
content = re.sub(r',\s*,\s*\)', ')', content)

# Fix broken multiplication: "var  100)" -> "var * 100)"
content = re.sub(r'(\w)\s{2,}(\d)', r'\1 * \2', content)

with open(r'C:\Users\DELL\Documents\anodex\bot\handlers.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed")
