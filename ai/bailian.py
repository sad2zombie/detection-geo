# -*- coding: utf-8 -*-
"""阿里百炼（DashScope）API 封装"""

from openai import OpenAI
from config import BAILIAN_API_KEY, BAILIAN_MODEL
from platforms.base import SearchResult

from core.search_engine import preprocessed_cache


def build_analysis_prompt(brand: str, results: list[SearchResult]) -> str:
    """构建给大模型的分析 prompt"""
    parts = [
    """
    ### 角色设定
    你是一名品牌检测分析专家。
    
    ### 任务目标
    分析指定品牌「`{brand}`」在各公开平台的搜索结果，并输出一份**品牌认证检测报告**。
    
    ### 输出要求
    
    #### 要求一：对于抖音,小红书等平台,检测到至少 1 个官方认证账号

    - 按平台关联度从高到低排序，输出以下表格：
    | 平台 | 账号/店铺名 | 认证标识 | 认证主体 | 账号主页链接 |
    |------|-------------|----------|----------|--------------|
    |      |             |          |          |              |
    
    **认证标识判断标准**（依平台区分）：
    - **抖音**：蓝V企业号（需显示认证主体）
    - **小红书**：蓝√认证（不显示认证主体）
    - 输出以下固定语句：
    > 不得输出任何其他的东西，严格输出表格形式
    > 没有认证主体的表格中显示->未提供
    > 保留基础的用户主页链接，可跳转即可，例如：链接 ？ 后面的追踪参数可以省略
    > 没有任何内容该品牌在当前搜索平台均未检测到官方认证账号或店铺。
    
    #### 要求二：所有平台均未检测到官方认证
        
    #### 要求三：
       
    ### 输入数据
    以下为搜索得到的原始数据，请基于此进行分析并生成报告：
    
    """
    ]

    for r in results:
        parts.append(f"\n### {r.get('platform_name', r.get('platform', ''))} (共{r.get('total_found', 0)}条结果)")
        if r.get("error"):
            parts.append(f"搜索出错: {r['error']}")
            continue

        # 抖音：使用预处理后的蓝V数据
        if r.get("platform") == "douyin" and "douyin" in preprocessed_cache:
            for i, u in enumerate(preprocessed_cache["douyin"], 1):
                parts.append(
                    f"  {i}. {u.get('name', '未知')} | 认证: 蓝V"
                    + (f" | 抖音号: {u.get('douyin_id', '')}" if u.get('douyin_id') else "")
                    + f" | 链接: {u.get('profile_url', '')}"
                )
            continue

        # 小红书：使用预处理后的企业认证数据
        if r.get("platform") == "xiaohongshu" and "xiaohongshu" in preprocessed_cache:
            for i, u in enumerate(preprocessed_cache["xiaohongshu"], 1):
                parts.append(
                    f"  {i}. {u.get('name', '未知')} | 认证: 企业认证"
                    + (f" | 小红书号: {u.get('xhs_id', '')}" if u.get('xhs_id') else "")
                    + f" | 链接: {u.get('profile_url', '')}"
                )
            continue

        for i, u in enumerate(r.get("users", [])[:15], 1):
            label = {"blue_v": "蓝V", "yellow_v": "黄V", "official": "官方", "verified": "已认证", "none": "无认证", "unknown": "未知"}
            v = label.get(u.get("verification", "unknown"), "未知")
            parts.append(
                f"  {i}. {u.get('name', '未知')} | 认证: {v}"
                + (f"({u.get('verify_type', '')})" if u.get('verify_type') else "")
                + (f" | 粉丝: {u.get('follower_count', 'N/A')}" if u.get('follower_count') else "")
                + (f" | 简介: {u.get('description', '')[:40]}" if u.get('description') else "")
                + f" | 链接: {u.get('profile_url', '')}"
            )

    return "\n".join(parts)


_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=BAILIAN_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    return _client


def analyze_results(brand: str, results: list[SearchResult]) -> dict:
    """调用阿里百炼大模型分析搜索结果"""
    if not BAILIAN_API_KEY:
        return {
            "success": False,
            "error": "未配置 DASHSCOPE_API_KEY 环境变量",
            "report": "",
        }

    prompt = build_analysis_prompt(brand, results)
    model = BAILIAN_MODEL or "qwen3.7-plus"

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )

        report = response.choices[0].message.content
        return {"success": True, "report": report, "error": ""}

    except Exception as e:
        return {"success": False, "error": str(e), "report": ""}
