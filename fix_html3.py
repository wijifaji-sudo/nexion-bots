import re

with open("bot/handlers.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Step 1: Convert *bold* -> <b>bold</b> and `code` -> <code>code</code>
content = ''.join(lines)
content = re.sub(r'\*([^*\n]+?)\*', r'<b>\1</b>', content)
content = re.sub(r'`([^`\n]+?)`', r'<code>\1</code>', content)
lines = content.splitlines(keepends=True)

# Step 2: Add parse_mode="HTML" to reply_text / reply_photo / send_message calls
# These may be single-line or multi-line. We track state.
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()
    
    # Check if this line starts a reply_text / reply_photo / send_message call
    is_api_call = any(kw in stripped for kw in [
        '.reply_text(', '.reply_photo(', '.send_message('
    ])
    
    if is_api_call:
        # Collect all lines of this statement (until we find the closing )
        block = [line]
        paren_depth = line.count('(') - line.count(')')
        j = i + 1
        while paren_depth > 0 and j < len(lines):
            block.append(lines[j])
            paren_depth += lines[j].count('(') - lines[j].count(')')
            j += 1
        
        block_text = ''.join(block)
        
        # Check if parse_mode already present
        if 'parse_mode' not in block_text:
            # Find the last ) and insert before it
            # The last line of the block has the closing )
            last_line = block[-1]
            # Find the position of the last )
            last_paren = last_line.rfind(')')
            if last_paren != -1:
                before = last_line[:last_paren]
                after = last_line[last_paren:]
                # Check if there's already content before the )
                content_stripped = before.rstrip()
                if content_stripped.endswith(','):
                    # Already has trailing comma
                    block[-1] = before + ' parse_mode="HTML"' + after
                elif content_stripped:
                    block[-1] = before + ', parse_mode="HTML"' + after
                else:
                    block[-1] = before + ' parse_mode="HTML"' + after
        
        new_lines.extend(block)
        i = j
    else:
        new_lines.append(line)
        i += 1

with open("bot/handlers.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Done - converted markdown to HTML with correct parse_mode placement")
