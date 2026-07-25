import re

with open(r'C:\Users\DELL\Documents\anodex\bot\handlers.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix pattern: "TEXT*TEXT*" where TEXT is same -> "*TEXT*"
# This handles unicode escapes before the first TEXT
def fix_dupe_bold(line):
    # Pattern: optional_unicode_escapes + TEXT + *TEXT*
    # where the two TEXTs are the same
    result = re.sub(
        r'((?:\\U[0-9a-fA-F]+\s*)*)([^*]+?)\*(\2)\*',
        lambda m: m.group(1) + '*' + m.group(2) + '*',
        line
    )
    return result

lines = content.split('\n')
new_lines = [fix_dupe_bold(line) for line in lines]
content = '\n'.join(new_lines)

with open(r'C:\Users\DELL\Documents\anodex\bot\handlers.py', 'w', encoding='utf-8') as f:
    f.write(content)

# Verify key areas
for i, line in enumerate(content.split('\n')[195:210], start=196):
    print(f"  {i}: {line.strip()[:120]}")
print("...")
for i, line in enumerate(content.split('\n')[660:690], start=661):
    if line.strip():
        print(f"  {i}: {line.strip()[:120]}")
print("...")
for i, line in enumerate(content.split('\n')[740:755], start=741):
    print(f"  {i}: {line.strip()[:120]}")
