"""Fix _fast_teach system prompt with explicit format rules."""
path = "docker/platform/provider_api.py"
with open(path, "r", encoding="utf-8-sig") as f:
    text = f.read()

# Find the _fast_teach function
old_common = (
    '    common = (\n'
    '        \"【排版：自然分段，不用分隔线，选项各占一行】\\\\n\"\n'
    '        \"你是一位中小学教师，用 Socratic 方式引导学生。回复简洁，不要多余文字。\\\\n\"\n'
    '    )'
)
new_common = (
    '    common = (\n'
    '        \"你是一位中小学教师，用 Socratic 方式引导学生。回复简洁清晰。\\\\n\"\n'
    '        \"## 格式规则（必须遵守）\\\\n\"\n'
    '        \"- 题目和选项必须换行，不能挤在一行\\\\n\"\n'
    '        \"- 每个选项单独一行，格式：A. 内容\\\\nB. 内容\\\\n\"\n'
    '        \"- 引导问题另起一段，不跟在选项后面\\\\n\"\n'
    '        \"- 不使用分隔线，用空行分段\\\\n\"\n'
    '        \"- 回复总长度不超过 400 字\\\\n\"\n'
    '        \"## 示范格式\\\\n\"\n'
    '        \"第1题\\\\n\"\n'
    '        \"小明有10个苹果，吃了3个，还剩几个？\\\\n\"\n'
    '        \"A. 5个\\\\n\"\n'
    '        \"B. 6个\\\\n\"\n'
    '        \"C. 7个\\\\n\"\n'
    '        \"D. 8个\\\\n\"\n'
    '        \"\\\\n\"\n'
    '        \"想一想，这是加法还是减法？\\\\n\"\n'
    '        \"[ANSWER_KEY:C] [KP_ID:数学/减法]\\\\n\"\n'
    '    )'
)

count = text.count(old_common)
print(f"Found {count} matches for old_common")
if count == 1:
    text = text.replace(old_common, new_common, 1)
    
    # Also bump max_tokens from 1024 to 1536
    text = text.replace('"max_tokens": 1024}', '"max_tokens": 1536}')
    
    import ast
    ast.parse(text)
    print("Syntax OK")
    
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(text)
else:
    print("ERROR: count != 1")
    # Show nearby text
    idx = text.find('common = (')
    if idx >= 0:
        print(repr(text[idx:idx+300]))
