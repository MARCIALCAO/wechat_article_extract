#!/usr/bin/env python3
"""
微信文章（中英文/多媒体排版）客户端内存 DOM 解析与 Markdown 离线整理工具
专门面向 AI Agent 及自动化流程设计的技术研究与个人文档归档工具：
1. 【默认独立输出目录】：默认将提取结果保存至独立的 ./output/ 目录，避免污染工作区。
2. 【精准标题与元数据提取】：向前扩展切片完整包含 #activity-name（真实大标题）、#js_name（公众号）、#js_author_name（作者）。
3. 【精准 URL 提取】：严格从 og:url、canonical link 或 msg_link 变量中提取当前文章真实链接，杜绝盲目匹配页面内推荐链接。
4. 【中英文全语言支持】：支持中文、英文及代码混排文章，自动计算有效正文字符数。
5. 【多标签页多文章消歧】：
   - 支持结构化列出全部打开的文章（--list / --json）
   - 支持按 URL、标题、公众号或正文关键词精准匹配（target）
   - 支持一键批量提取全部打开的文章（--all）
"""

import argparse
import ctypes
import ctypes.wintypes
import datetime
import json
import os
import re
import subprocess
import sys
from lxml import etree

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.wintypes.DWORD),
        ("PartitionId", ctypes.wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.wintypes.DWORD),
        ("Protect", ctypes.wintypes.DWORD),
        ("Type", ctypes.wintypes.DWORD),
    ]


def get_wechat_renderer_pids():
    """获取所有微信浏览器渲染进程 PID（按启动时间降序排序）"""
    if sys.platform != "win32":
        return []
    try:
        cmd = 'powershell "Get-Process | Where-Object { $_.ProcessName -match \'WeChatAppEx|Weixin\' } | Sort-Object StartTime -Descending | Select-Object -ExpandProperty Id"'
        res = subprocess.run(cmd, capture_output=True, text=True)
        return [int(line.strip()) for line in res.stdout.splitlines() if line.strip().isdigit()]
    except Exception:
        return []


def scan_all_active_articles(filter_keyword=None):
    """
    扫描微信渲染进程内存，提取所有已渲染且真实的完整文章。
    向前扩展切片，完整捕获 #activity-name 真实主标题。
    """
    if sys.platform != "win32":
        return [], "本功能当前专为 Windows 微信客户端设计。"

    pids = get_wechat_renderer_pids()
    if not pids:
        return [], "未检测到运行中的微信进程，请确认微信是否已启动并打开了文章。"

    kernel32 = ctypes.windll.kernel32
    target_u16 = 'id="js_content"'.encode('utf-16-le')
    target_u8 = 'id="js_content"'.encode('utf-8')
    act_u16 = 'id="activity-name"'.encode('utf-16-le')
    act_u8 = 'id="activity-name"'.encode('utf-8')
    img_u16 = 'id="img-content"'.encode('utf-8')
    img_u16_le = 'id="img-content"'.encode('utf-16-le')
    div_u16 = '<div'.encode('utf-16-le')
    div_u8 = '<div'.encode('utf-8')

    raw_candidates = []

    for pid in pids:
        h_proc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h_proc:
            continue
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION()
        while kernel32.VirtualQueryEx(h_proc, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            if mbi.State == MEM_COMMIT and (mbi.Protect in (0x02, 0x04, 0x20, 0x40)):
                if mbi.RegionSize > 50 * 1024:
                    buffer = ctypes.create_string_buffer(mbi.RegionSize)
                    bytes_read = ctypes.c_size_t()
                    if kernel32.ReadProcessMemory(h_proc, ctypes.c_void_p(addr), buffer, mbi.RegionSize, ctypes.byref(bytes_read)):
                        raw = buffer.raw[:bytes_read.value]
                        
                        for enc, tag, act_tag, img_tag, d_tag in [
                            ('utf-16-le', target_u16, act_u16, img_u16_le, div_u16),
                            ('utf-8', target_u8, act_u8, img_u16, div_u8)
                        ]:
                            pos = 0
                            while True:
                                pos_js = raw.find(tag, pos)
                                if pos_js == -1:
                                    break
                                
                                # 向前扩展切片，囊括 #activity-name 与 #img-content
                                pos_act = raw.rfind(act_tag, 0, pos_js)
                                pos_img = raw.rfind(img_tag, 0, pos_js)
                                valid_anchors = [p for p in (pos_act, pos_img) if p != -1]
                                start_anchor = min(valid_anchors) if valid_anchors else max(0, pos_js - 10000)
                                
                                div_s = raw.rfind(d_tag, 0, start_anchor)
                                if div_s == -1:
                                    div_s = max(0, start_anchor - 200)
                                
                                slice_data = raw[div_s:]
                                txt = slice_data.decode(enc, errors='ignore')
                                
                                # 解析 HTML
                                full_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{txt}</body></html>"
                                tree = etree.HTML(full_html.encode('utf-8'))
                                if tree is not None:
                                    jc = tree.xpath('//*[@id="js_content"]')
                                    if jc:
                                        jc_text = "".join(jc[0].itertext()).strip()
                                        
                                        # 排除未填充数据的模板
                                        if 'content_noencode.DATA' not in jc_text and '$content_noencode$' not in jc_text:
                                            valid_chars = len(re.findall(r'[\w\u4e00-\u9fa5]', jc_text))
                                            
                                            if valid_chars >= 30:
                                                # 提取真实主标题
                                                title_nodes = tree.xpath('//*[@id="activity-name"]//text()') or tree.xpath('//h1[contains(@class, "title")]//text()')
                                                raw_title = "".join(title_nodes).strip()
                                                
                                                title = ""
                                                if raw_title and '$' not in raw_title and 'malicious_title' not in raw_title:
                                                    title = raw_title
                                                else:
                                                    first_h = tree.xpath('.//h1//text() | .//h2//text()')
                                                    first_h_clean = [t.strip() for t in first_h if t.strip() and '$' not in t and 'DATA' not in t and len(t.strip()) > 3]
                                                    title = first_h_clean[0] if first_h_clean else "微信图文文章"

                                                # 提取公众号名称与作者
                                                raw_acc = "".join(tree.xpath('//*[@id="js_name"]//text()')).strip()
                                                account = raw_acc if ('$' not in raw_acc and 'DATA' not in raw_acc) else ""
                                                
                                                raw_auth = "".join(tree.xpath('//*[@id="js_author_name"]//text()')).strip()
                                                author = raw_auth if ('$' not in raw_auth and 'DATA' not in raw_auth) else ""

                                                # 【精准提取 Canonical URL】：严格校验元数据，杜绝盲目匹配页面内的其他无关链接
                                                article_url = ""
                                                og_url = "".join(tree.xpath('//meta[@property="og:url"]/@content')).strip()
                                                canonical_url = "".join(tree.xpath('//link[@rel="canonical"]/@href')).strip()
                                                if og_url and og_url.startswith("http") and "$" not in og_url:
                                                    article_url = og_url
                                                elif canonical_url and canonical_url.startswith("http") and "$" not in canonical_url:
                                                    article_url = canonical_url
                                                else:
                                                    # 从 JavaScript msg_link 变量提取
                                                    msg_link_m = re.search(r'var\s+msg_link\s*=\s*["\'](https?://mp\.weixin\.qq\.com/s[^"\']+)["\']', txt)
                                                    if msg_link_m:
                                                        article_url = msg_link_m.group(1).replace("&amp;", "&")
                                                
                                                raw_candidates.append({
                                                    'pid': pid,
                                                    'addr': hex(addr),
                                                    'addr_int': addr,
                                                    'enc': enc,
                                                    'title': title,
                                                    'account': account,
                                                    'author': author,
                                                    'url': article_url,
                                                    'char_count': valid_chars,
                                                    'total_len': len(txt),
                                                    'jc_text': jc_text,
                                                    'jc_element': jc[0],
                                                    'raw_html': txt
                                                })
                                pos = pos_js + len(tag)
            addr += mbi.RegionSize
        kernel32.CloseHandle(h_proc)

    # 核心排序：进程启动时间倒序（最新进程在前） + 同进程内内存地址倒序（最高/最晚分配地址在前）
    pid_order = {p: i for i, p in enumerate(pids)}
    raw_candidates.sort(key=lambda x: (pid_order.get(x['pid'], 9999), -x['addr_int']))

    # 以正文首段 120 字符去重聚合，优先保留最新渲染且内容最完整的一份
    unique_articles = {}
    for item in raw_candidates:
        fingerprint = re.sub(r'\s+', '', item['jc_text'][:120])
        if not fingerprint:
            continue
        if fingerprint not in unique_articles or item['char_count'] > unique_articles[fingerprint]['char_count']:
            unique_articles[fingerprint] = item

    results = list(unique_articles.values())

    # 关键词 / 标题过滤
    if filter_keyword:
        kw = filter_keyword.strip()
        clean_kw = re.sub(r'https?://mp\.weixin\.qq\.com/s/?', '', kw).split('?')[0] if kw.startswith('http') else kw
        filtered = []
        for a in results:
            if (kw in a['title'] or kw in a['account'] or kw in a['author'] 
                or (clean_kw and clean_kw in a['raw_html']) or kw in a['jc_text']):
                # 如果用户传入了有效 URL，将该 URL 赋予当前文章
                if kw.startswith("http"):
                    a['url'] = kw
                filtered.append(a)
        return filtered, None

    return results, None


def convert_dom_to_markdown(article_info, user_provided_url=None):
    """将 DOM 节点转换为结构化 Markdown"""
    jc_el = article_info['jc_element']
    title = article_info['title']
    account = article_info.get('account', '')
    author = article_info.get('author', '')
    url = user_provided_url or article_info.get('url', '')

    lines = []
    for el in jc_el.xpath('.//*[self::h1 or self::h2 or self::h3 or self::h4 or self::p or self::section or self::div or self::pre]'):
        has_block_child = any(c.tag in ('h1', 'h2', 'h3', 'h4', 'p', 'section', 'div', 'pre') for c in el if isinstance(c.tag, str))
        if not has_block_child:
            tag = el.tag.lower()
            t_str = "".join(el.itertext()).replace('\xa0', ' ').strip()
            
            if tag == 'pre':
                lines.append(f"\n```\n{t_str}\n```\n")
            elif t_str:
                if tag in ('h1', 'h2', 'h3', 'h4'):
                    level = '#' * int(tag[1])
                    lines.append(f"\n{level} {t_str}\n")
                else:
                    lines.append(t_str)
                    
            imgs = el.xpath('.//img')
            for img in imgs:
                src = img.get('data-src') or img.get('src') or ''
                if 'mmbiz' in src:
                    lines.append(f"\n![]({src})\n")

    clean_lines = []
    prev = ""
    ignored_ui = {"确认提交投诉", "取消", "投诉", "阅读原文", "喜欢此内容的人还喜欢", "写留言", "已关注", "关注"}
    for l in lines:
        l_s = l.strip()
        if not l_s or l_s in ignored_ui or l_s == prev:
            continue
        prev = l_s
        clean_lines.append(l)

    pubtime = datetime.datetime.now().strftime("%Y-%m-%d")
    md_header = [f"# {title}\n\n"]
    meta_parts = []
    if author:
        meta_parts.append(f"作者：{author}")
    if account:
        meta_parts.append(f"公众号：{account}")
    meta_parts.append(f"提取时间：{pubtime}")
    
    if meta_parts:
        md_header.append(f"> {' ｜ '.join(meta_parts)}\n")
    if url:
        md_header.append(f"> 原文链接：{url}\n")
    md_header.append("---\n\n")

    return title, "".join(md_header) + "\n\n".join(clean_lines)


def main():
    if sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(description="微信文章客户端内存 DOM 解析与 Markdown 离线整理工具")
    parser.add_argument("target", nargs="?", default=None, help="目标文章标题、公众号、URL或正文关键词（可选）")
    parser.add_argument("--list", action="store_true", help="列出当前微信客户端内存中所有打开的文章")
    parser.add_argument("--all", action="store_true", help="批量解析并保存内存中打开的所有文章")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出扫描结果（面向 Agent 结构化调用）")
    parser.add_argument("--output-dir", default="output", help="输出 Markdown 文件目录（默认 ./output/ 文件夹）")
    args = parser.parse_args()

    articles, err = scan_all_active_articles(args.target)
    if err:
        print(f"❌ 错误: {err}")
        sys.exit(1)

    if not articles:
        print("⚠️ 未在微信内存中发现匹配的文章。请确认微信已启动并打开了目标文章。")
        sys.exit(1)

    # 1. 列表模式
    if args.list:
        if args.json:
            out_list = [{
                "title": a["title"],
                "account": a.get("account", ""),
                "author": a.get("author", ""),
                "url": a.get("url", ""),
                "pid": a["pid"],
                "char_count": a["char_count"],
                "preview": a["jc_text"][:120]
            } for a in articles]
            print(json.dumps(out_list, ensure_ascii=False, indent=2))
        else:
            print(f"📋 发现 {len(articles)} 篇在内存中打开的有效文章：")
            for i, a in enumerate(articles, 1):
                meta_info = f"字数: {a['char_count']} | PID: {a['pid']}"
                if a.get('account'):
                    meta_info += f" | 公众号: {a['account']}"
                print(f"  [{i}] 《{a['title']}》 ({meta_info})")
                print(f"      预览: {' '.join(a['jc_text'][:80].split())}...\n")
        return

    # 2. 提取并保存模式
    target_articles = articles if args.all else [articles[0]]
    os.makedirs(args.output_dir, exist_ok=True)

    user_url = args.target if (args.target and args.target.startswith("http")) else None

    for a in target_articles:
        title, md_content = convert_dom_to_markdown(a, user_provided_url=user_url)
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)
        out_path = os.path.join(args.output_dir, f"{safe_title}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"✅ 成功提取: {out_path}")
        print(f"   标题: 《{title}》 | 正文字符数: {len(md_content)}\n")


if __name__ == "__main__":
    main()
