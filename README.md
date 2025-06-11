# FileSummary
用于xxxbot-pad的插件，自动进行文件总结，目前仅支持pdf、txt、md这三类文件，

# 配置文件说明

[FileSummary]
enable = true

[FileSummary.OpenAI]
enable = true
api-key = "xxxxx"  # 请替换为实际的 API Key
model = "gemini-2.5-flash-preview-05-20" # 请替换为实际的model
base-url = "https://xxxxxx/v1"  # 请替换为实际的API URL，只支持openai兼容API
prompt= "请对以下文档内容进行全面总结，要求：\n- 提炼出文档中的主要观点和核心内容。\n- 梳理出文档的结构层次、章节要点。\n- 突出关键结论、重要数据、建议或行动项（如有）。\n- 保持总结简洁清晰、逻辑性强，方便阅读。\n- 语言风格保持正式、客观、中立。\n\n需要输出两部分：\n1、简明摘要（100-300字）\n2、详细分段总结（按文档结构，逐段列出要点）"
http-proxy = ""  # 如果需要代理可以在这里设置

# 使用说明
将文件转发给AI微信，后台将会自动调用对应的API接口进行文件解析。

# 注意事项
当前只支持openai兼容API！
