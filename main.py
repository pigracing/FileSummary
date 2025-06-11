from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase
from utils.decorators import on_text_message, on_file_message, on_article_message
import aiohttp
import asyncio
import re
import os
import sys
import tomllib
import time
from loguru import logger
from typing import Dict, Optional, TYPE_CHECKING
import json
import html
import xml.etree.ElementTree as ET
from urllib.parse import quote
import random
import base64
import mimetypes


class FileSummary(PluginBase):
    description = "自动总结文件内容"
    author = "pigracing"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.name = "FileSummary"
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        self.config = config.get("FileSummary", {})
        openai_config = self.config.get("OpenAI", {})
        self.enable = self.config.get("enable","")
        self.openai_enable = openai_config.get("enable", False)
        self.openai_api_key = openai_config.get("api-key", "")
        self.model = openai_config.get("model", "")
        self.openai_base_url = openai_config.get("base-url", "")
        self.http_proxy = openai_config.get("http-proxy", "")
        self.prompt = openai_config.get("prompt", "请对以下文档内容进行全面总结，要求：\n- 提炼出文档中的主要观点和核心内容。\n- 梳理出文档的结构层次、章节要点。\n- 突出关键结论、重要数据、建议或行动项（如有）。\n- 保持总结简洁清晰、逻辑性强，方便阅读。\n- 语言风格保持正式、客观、中立。\n\n需要输出两部分：\n1️⃣ 简明摘要（100-300字）\n2️⃣ 详细分段总结（按文档结构，逐段列出要点）")

        # 加载新的配置项
        # 总结命令触发词
        self.sum_trigger = self.config.get("sum_trigger", "/总结")
        # 构建触发词列表，包括基本触发词和衍生触发词
        self.summary_triggers = [
            self.sum_trigger,
            f"{self.sum_trigger}链接",
            f"{self.sum_trigger}内容",
            f"{self.sum_trigger}一下",
            f"帮我{self.sum_trigger}",
            "summarize"
        ]

        # 追问命令触发词
        self.qa_trigger = self.config.get("qa_trigger", "问")

        # 自动总结开关
        self.auto_sum = self.config.get("auto_sum", True)

        logger.info(f"FileSummary插件配置加载完成: 触发词={self.sum_trigger}, 自动总结={self.auto_sum}")
        logger.info(f"OpenAIEnable: {self.openai_enable}")
        logger.info(f"OpenAIAPIKey: {self.openai_api_key}")
        logger.info(f"OpenAIBaseUrl: {self.openai_base_url}")

        # 存储最近的链接和卡片信息
        self.recent_urls = {}  # 格式: {chat_id: {"url": url, "timestamp": timestamp}}
        self.recent_cards = {}  # 格式: {chat_id: {"info": card_info, "timestamp": timestamp}}

        # 存储总结内容缓存
        self.summary_cache = {}  # 格式: {chat_id: {"summary": summary, "original_content": content, "timestamp": timestamp}}

        self.http_session: Optional[aiohttp.ClientSession] = None
        

        if not self.openai_enable or not self.openai_api_key or not self.openai_base_url:
            logger.warning("openai配置不完整，自动总结功能将被禁用")
            self.openai_enable = False
        
        # 创建下载目录
        self.download_dir = os.path.join(os.path.dirname(__file__), "downloads")
        os.makedirs(self.download_dir, exist_ok=True)

        logger.info(f"FileSummary插件初始化完成，自动下载: {self.download_dir}")
    
    
    @on_xml_message(priority=100)  # 使用最高优先级确保最先处理
    async def handle_xml_quote(self, bot: WechatAPIClient, message: dict):
        """专门处理XML格式的引用消息"""
        logger.debug("FileSummary---on_xml_quote_message")
        logger.debug(message)
        if not self.enable:
            logger.debug("FileSummary---on_xml_quote_message--not enable")
            return True
        else:
            logger.debug("FileSummary---on_xml_quote_message--enable")
            logger.debug(message)
            msg_type = message["MsgType"]
            if msg_type == 49:
                try:
                    logger.debug("FileSummary-----处理文件消息")
                    # message["Content"] = message["Content"][:100]
                    # logger.debug(message)
                    # 获取图片消息的关键信息
                    msg_id = message.get("MsgId")
                    from_wxid = message.get("FromWxid")
                    sender_wxid = message.get("SenderWxid")
                    newMsgId = message.get("NewMsgId")
                    isGroup = message.get("IsGroup")
                    logger.info(f"收到图片消息: MsgId={msg_id}, FromWxid={from_wxid}, SenderWxid={sender_wxid},newMsgId={newMsgId}, IsGroup={isGroup}")
                    if isGroup:
                        logger.info(f"群聊: MsgId={msg_id}, FromWxid={from_wxid}, SenderWxid={sender_wxid},newMsgId={newMsgId}, IsGroup={isGroup}")
                    else:
                        try:
                            # 解析XML内容
                            root = ET.fromstring(message["Content"])
                            appmsg = root.find("appmsg")
                            if appmsg is None:
                                return True

                            type_element = appmsg.find("type")
                            if type_element is None:
                                return True

                            type_value = int(type_element.text)
                            logger.info(f"FileDownloader: XML消息类型: {type_value}")

                            # 检测是否是文件消息（类型6）
                            if type_value == 6:
                                logger.info("FileDownloader: 检测到文件消息")

                                # 提取文件信息
                                title = appmsg.find("title").text
                                appattach = appmsg.find("appattach")
                                attach_id = appattach.find("attachid").text
                                file_extend = appattach.find("fileext").text
                                total_len = int(appattach.find("totallen").text)

                                logger.info(f"FileDownloader: 文件名: {title}")
                                logger.info(f"FileDownloader: 文件扩展名: {file_extend}")
                                logger.info(f"FileDownloader: 附件ID: {attach_id}")
                                logger.info(f"FileDownloader: 文件大小: {total_len}")

                                # 发送通知
                                await bot.send_text_message(
                                    message["FromWxid"],
                                    f"FileDownloader: 正在下载文件...\n文件名: {title}"
                                )

                                # 使用 /Tools/DownloadFile API 下载文件
                                logger.info("FileDownloader: 开始下载文件...")

                                try:
                                    # 分段下载大文件
                                    # 每次下载 64KB
                                    chunk_size = 64 * 1024  # 64KB
                                    app_id = appmsg.get("appid", "")

                                    # 创建一个字节数组来存储完整的文件数据
                                    file_data = bytearray()

                                    # 计算需要下载的分段数量
                                    chunks = (total_len + chunk_size - 1) // chunk_size  # 向上取整

                                    logger.info(f"FileDownloader: 开始分段下载文件，总大小: {total_len} 字节，分 {chunks} 段下载")

                                    # 分段下载
                                    for i in range(chunks):
                                        start_pos = i * chunk_size
                                        # 最后一段可能不足 chunk_size
                                        current_chunk_size = min(chunk_size, total_len - start_pos)

                                        logger.info(f"FileDownloader: 下载第 {i+1}/{chunks} 段，起始位置: {start_pos}，大小: {current_chunk_size} 字节")

                                        async with aiohttp.ClientSession() as session:
                                            # 设置较长的超时时间
                                            timeout = aiohttp.ClientTimeout(total=60)  # 1分钟

                                            # 构造请求参数
                                            json_param = {
                                                "AppID": app_id,
                                                "AttachId": attach_id,
                                                "DataLen": total_len,
                                                "Section": {
                                                    "DataLen": current_chunk_size,
                                                    "StartPos": start_pos
                                                },
                                                "UserName": "",  # 可选参数
                                                "Wxid": bot.wxid
                                            }

                                            logger.info(f"FileDownloader: 调用下载文件API: AttachId={attach_id}, 起始位置: {start_pos}, 大小: {current_chunk_size}")
                                            response = await session.post(
                                                'http://127.0.0.1:9011/api/Tools/DownloadFile',
                                                json=json_param,
                                                timeout=timeout
                                            )

                                            # 处理响应
                                            try:
                                                json_resp = await response.json()

                                                if json_resp.get("Success"):
                                                    data = json_resp.get("Data")

                                                    # 尝试从不同的响应格式中获取文件数据
                                                    chunk_data = None
                                                    if isinstance(data, dict):
                                                        if "buffer" in data:
                                                            chunk_data = base64.b64decode(data["buffer"])
                                                        elif "data" in data and isinstance(data["data"], dict) and "buffer" in data["data"]:
                                                            chunk_data = base64.b64decode(data["data"]["buffer"])
                                                        else:
                                                            try:
                                                                chunk_data = base64.b64decode(str(data))
                                                            except:
                                                                logger.error(f"FileDownloader: 无法解析文件数据: {data}")
                                                    elif isinstance(data, str):
                                                        try:
                                                            chunk_data = base64.b64decode(data)
                                                        except:
                                                            logger.error(f"FileDownloader: 无法解析文件数据字符串")

                                                    if chunk_data:
                                                        # 将分段数据添加到完整文件中
                                                        file_data.extend(chunk_data)
                                                        logger.info(f"FileDownloader: 第 {i+1}/{chunks} 段下载成功，大小: {len(chunk_data)} 字节")
                                                    else:
                                                        logger.warning(f"FileDownloader: 第 {i+1}/{chunks} 段数据为空")
                                                else:
                                                    error_msg = json_resp.get("Message", "Unknown error")
                                                    logger.error(f"FileDownloader: 第 {i+1}/{chunks} 段下载失败: {error_msg}")
                                            except Exception as e:
                                                logger.error(f"FileDownloader: 解析第 {i+1}/{chunks} 段响应失败: {e}")

                                    # 检查文件是否下载完整
                                    if len(file_data) > 0:
                                        logger.info(f"FileDownloader: 文件下载成功: AttachId={attach_id}, 实际大小: {len(file_data)} 字节")

                                        # 保存文件
                                        safe_title = self.get_safe_filename(title)
                                        file_path = os.path.join(self.download_dir, f"{safe_title}.{file_extend}")
                                        with open(file_path, "wb") as f:
                                            f.write(file_data)

                                        logger.info(f"FileDownloader: 文件下载成功: {file_path}, 大小: {len(file_data)} 字节")
                                        out_message = await self.call_ai(file_path)
                                        await bot.send_text_message(message["FromWxid"], out_message)
                                    else:
                                        logger.warning("FileDownloader: 文件数据为空")
                                except Exception as e:
                                    logger.error(f"FileDownloader: 下载文件时发生异常: {e}")
                        except Exception as e:
                            logger.error(f"FileDownloader: 处理XML消息时发生错误: {str(e)}")
                            return True
                        return False
                    return True
                except Exception as e:
                    logger.error(f"处理图片消息失败: {e}")
                    return True
        
                return False

        return True
    
    async def call_ai(self, filename: str) -> str:
        try:
            logger.debug("call_ai")
            data_uri = self.file_to_base64(filename)
            logger.debug("data_uri:"+data_uri[0:30])
            messages = [
                {
                    "role":"system",
                    "content": [
                        { "type": "text", "text": self.prompt }
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {
                        "type": "text",
                        "text": "总结这份文档"
                        },
                        {
                        "type": "document",
                        "document": {"url":data_uri}
                        }
                    ]
                }
            ]
            url = f"{self.openai_base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "stream": False,
                "messages": messages,
                "temperature": 0.7
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    response_text = await response.text()

                    if response.status != 200:
                        raise RuntimeError(f"OpenAI API 请求失败: {response.status} - {response_text}")

                    try:
                        data = json.loads(response_text)
                    except json.JSONDecodeError:
                        raise RuntimeError(f"响应无法解析为 JSON（Content-Type: {response.headers.get('Content-Type')}）：\n{response_text}")

                    # 解析内容
                    text = data["choices"][0]["message"]["content"]

                    return text
        except Exception as e:
            logger.error(f"调用 OpenAI API 失败: {e}")
            return False


    def get_safe_filename(self, filename: str) -> str:
        """生成安全的文件名，移除不允许的字符

        Args:
            filename: 原始文件名

        Returns:
            str: 安全的文件名
        """
        safe_name = re.sub(r'[\\/*?:"<>|]', '_', filename)
        # 限制文件名长度
        if len(safe_name) > 200:
            safe_name = safe_name[:200]
        return safe_name
    


    def file_to_base64(self,file_path):
        """
        将本地文件转换为base64编码

        Args:
            file_path (str): 文件路径

        Returns:
            dict: 包含文件信息的字典
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return {"error": "文件不存在"}

            # 获取文件大小
            file_size = os.path.getsize(file_path)

            # 获取文件扩展名
            _, file_extension = os.path.splitext(file_path)

            # 获取MIME类型
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type is None:
                # 根据扩展名设置默认MIME类型
                mime_type = self.get_mime_type_by_extension(file_extension.lower())

            # 读取文件并转换为base64
            with open(file_path, 'rb') as file:
                file_content = file.read()
                base64_string = base64.b64encode(file_content).decode('utf-8')

            # 生成Data URI格式
            data_uri = f"data:{mime_type};base64,{base64_string}"

            return data_uri

        except Exception as e:
            return {"error": f"处理文件时出错: {str(e)}"}


    def get_mime_type_by_extension(extension):
        """
        根据文件扩展名获取MIME类型

        Args:
            extension (str): 文件扩展名

        Returns:
            str: MIME类型
        """
        mime_types = {
            # 图片
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon',

            # 文档
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.txt': 'text/plain',
            '.rtf': 'application/rtf',

            # 音频
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.ogg': 'audio/ogg',
            '.m4a': 'audio/mp4',
            '.flac': 'audio/flac',

            # 视频
            '.mp4': 'video/mp4',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.wmv': 'video/x-ms-wmv',
            '.flv': 'video/x-flv',
            '.webm': 'video/webm',

            # 压缩文件
            '.zip': 'application/zip',
            '.rar': 'application/x-rar-compressed',
            '.7z': 'application/x-7z-compressed',
            '.tar': 'application/x-tar',
            '.gz': 'application/gzip',

            # 代码文件
            '.html': 'text/html',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.json': 'application/json',
            '.xml': 'application/xml',
            '.py': 'text/x-python',
            '.java': 'text/x-java-source',
            '.cpp': 'text/x-c++src',
            '.c': 'text/x-csrc',

            # 其他
            '.bin': 'application/octet-stream',
            '.exe': 'application/x-msdownload',
            '.dmg': 'application/x-apple-diskimage',
        }

        return mime_types.get(extension, 'application/octet-stream')
