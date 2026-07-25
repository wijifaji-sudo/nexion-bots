import re

with open("bot/handlers.py", "r", encoding="utf-8") as f:
    content = f.read()

content = re.sub(r'\*([^*\n]+?)\*', r'<b>\1</b>', content)
content = re.sub(r'`([^`\n]+?)`', r'<code>\1</code>', content)

with open("bot/handlers.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done")
