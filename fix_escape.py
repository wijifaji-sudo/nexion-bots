with open("bot/handlers.py", "r", encoding="utf-8") as f:
    content = f.read()

# Escape < and > inside <code> blocks that aren't real HTML tags
# Replace <user_id> <amount> <uid> <amt> <chain> <address> <msg> inside code tags
replacements = {
    "<user_id>": "&lt;user_id&gt;",
    "<amount>": "&lt;amount&gt;",
    "<uid>": "&lt;uid&gt;",
    "<amt>": "&lt;amt&gt;",
    "<chain>": "&lt;chain&gt;",
    "<address>": "&lt;address&gt;",
    "<msg>": "&lt;msg&gt;",
}

for old, new in replacements.items():
    content = content.replace(old, new)

with open("bot/handlers.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done - escaped angle brackets in code blocks")
