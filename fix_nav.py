import re

with open("bot/handlers.py", "r", encoding="utf-8") as f:
    content = f.read()

# Pattern 1: multi-line edit_message_text with reply_markup
# await query.edit_message_text(\n    text, reply_markup=...\n)
content = re.sub(
    r'await query\.edit_message_text\(\s*\n\s*(\w+),\s*reply_markup=([^)]+)\)',
    r'await nav(query, context, \1, \2)',
    content
)

# Pattern 2: single-line with reply_markup
# await query.edit_message_text(text, reply_markup=...)
content = re.sub(
    r'await query\.edit_message_text\(([^,)]+),\s*reply_markup=([^)]+)\)',
    r'await nav(query, context, \1, \2)',
    content
)

# Pattern 3: multi-line with just text, no reply_markup
# await query.edit_message_text(\n    text\n)
content = re.sub(
    r'await query\.edit_message_text\(\s*\n\s*(\w+)\s*\)',
    r'await nav(query, context, \1)',
    content
)

# Pattern 4: single-line with just text
# await query.edit_message_text(text)
content = re.sub(
    r'await query\.edit_message_text\(([^,)]+)\)',
    r'await nav(query, context, \1)',
    content
)

remaining = content.count('edit_message_text')
print(f"Remaining edit_message_text calls: {remaining}")

with open("bot/handlers.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done")
