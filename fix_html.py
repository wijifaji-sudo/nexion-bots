import re

with open("bot/handlers.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace *bold* with <b>bold</b> - non-greedy, single line only
content = re.sub(r'\*([^*\n]+?)\*', r'<b>\1</b>', content)

# Replace `code` with <code>code</code> - single line only
content = re.sub(r'`([^`\n]+?)`', r'<code>\1</code>', content)

# Add parse_mode="HTML" to all reply_text calls that don't already have it
content = re.sub(
    r'(\.reply_text\([^)]+?)(\))',
    lambda m: m.group(1) + ', parse_mode="HTML"' + m.group(2)
        if 'parse_mode' not in m.group(1) else m.group(0),
    content
)

# Add parse_mode="HTML" to reply_photo calls that don't already have it
content = re.sub(
    r'(\.reply_photo\([^)]+?)(\))',
    lambda m: m.group(1) + ', parse_mode="HTML"' + m.group(2)
        if 'parse_mode' not in m.group(1) else m.group(0),
    content
)

# Add parse_mode="HTML" to send_message calls that don't already have it  
content = re.sub(
    r'(\.send_message\([^)]+?)(\))',
    lambda m: m.group(1) + ', parse_mode="HTML"' + m.group(2)
        if 'parse_mode' not in m.group(1) else m.group(0),
    content
)

with open("bot/handlers.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done - converted all markdown to HTML")
