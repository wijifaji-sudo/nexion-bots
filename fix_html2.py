import re

with open("bot/handlers.py", "r", encoding="utf-8") as f:
    content = f.read()

# First: remove ALL "parse_mode=\"HTML\"" that ended up in wrong places
# We'll re-add them correctly below
content = content.replace(', parse_mode="HTML")', '__REMOVE__PM__')
content = content.replace(', parse_mode="HTML"\n', '__REMOVE__PM__\n')
content = content.replace(',\n                    parse_mode="HTML"', '')

# Now re-add parse_mode="HTML" ONLY to reply_text, reply_photo, send_message calls
# We need to find the last ) of these specific calls and add before it

def add_parse_mode(match):
    return match.group(0).rstrip(')') + ', parse_mode="HTML")'

# reply_text("...", ...)  - single line
content = re.sub(r'await (?:update\.message\.reply_text|context\.bot\.send_message|update\.message\.reply_photo)\([^)]*\)', add_parse_mode, content)

# Clean up any double parse_mode
content = content.replace('parse_mode="HTML", parse_mode="HTML"', 'parse_mode="HTML"')

# Clean up __REMOVE__PM__ markers
content = content.replace('__REMOVE__PM__', '')

with open("bot/handlers.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done - fixed parse_mode placement")
