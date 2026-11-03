#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
求职助手：找岗与投递路径连通性探测脚本

用途：
- 对企业招聘官网、BOSS 直聘公开搜索页、猎聘公开搜索页进行基础连通性探测。
- 不登录、不提交简历、不读取私人消息、不执行真实投递。
- 默认验证公开页面；可选美团公开岗位样本只调用列表与详情读取接口。

运行方式：
    python probe.py

输出：
    results/probe_report.json   结构化结果
    results/probe_report.md     可读报告
"""

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin

import requests
import yaml
from bs4 import BeautifulSoup

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

HEADERS = {
    "User-Agent": "interview-copilot-public-probe/0.1",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

TIMEOUT = 15


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def fetch(url: str) -> dict:
    """获取单个 URL，返回基础元数据，不抛异常。"""
    result = {
        "url": url,
        "ok": False,
        "status_code": None,
        "elapsed_ms": None,
        "title": None,
        "content_length": None,
        "indicators": {},
        "page_state": "request_failed",
        "final_url": None,
        "body_sha256": None,
        "job_content_status": "not_verified",
        "application_status": "not_tested",
        "feedback_status": "not_tested",
        "error": None,
    }
    try:
        start = time.time()
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        elapsed = (time.time() - start) * 1000
        result["status_code"] = resp.status_code
        result["elapsed_ms"] = round(elapsed, 2)
        result["content_length"] = len(resp.content)
        result["ok"] = resp.status_code == 200
        result["final_url"] = resp.url
        result["body_sha256"] = hashlib.sha256(resp.content).hexdigest()
        result["content_type"] = resp.headers.get("Content-Type", "")
        if not result["ok"]:
            result["page_state"] = "http_error"
            return result
        if "html" not in result["content_type"].lower():
            result["page_state"] = "non_html"
            return result

        soup = BeautifulSoup(resp.content, "html.parser")
        title_tag = soup.find("title")
        result["title"] = title_tag.get_text(strip=True) if title_tag else None
        result["script_count"] = len(soup.find_all("script"))
        result["public_links"] = [
            urljoin(resp.url, a["href"])
            for a in soup.find_all("a", href=True)
            if urljoin(resp.url, a["href"]).startswith(("https://", "http://"))
        ][:20]
        # 仅记录服务端 HTML 中的正文，脚本中的 login/captcha 字符串不作验证证据。
        for node in soup.find_all(["script", "style", "template", "head"]):
            node.decompose()
        visible_root = soup.body if soup.body is not None else soup
        visible_text = visible_root.get_text(" ", strip=True)
        result["visible_text_chars"] = len(visible_text)
        result["text_excerpt"] = visible_text[:100]
        lower_text = (str(result["title"] or "") + " " + visible_text).lower()
        result["indicators"] = {
            "has_captcha_keyword": any(
                kw in lower_text for kw in ["验证码", "captcha", "滑块", "安全验证", "人机验证"]
            ),
            "has_login_keyword": any(
                kw in lower_text for kw in ["登录", "login", "扫码登录", "请登录"]
            ),
            "has_block_keyword": any(
                kw in lower_text for kw in ["访问频繁", "请求过于频繁", "blocked"]
            ),
        }
        challenge_terms = ["安全验证", "人机验证", "请完成验证", "访问频繁", "请求过于频繁", "access denied"]
        is_challenge = any(kw in lower_text for kw in challenge_terms) and len(visible_text) < 300
        if is_challenge:
            result["page_state"] = "verification_required"
        elif not visible_text:
            result["page_state"] = "html_shell" if result["script_count"] else "empty_html"
        else:
            result["page_state"] = "html_content"
    except requests.exceptions.Timeout:
        result["error"] = "timeout"
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"connection_error: {type(e).__name__}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return result


def probe_meituan_public_job() -> dict:
    """读取一页中的一个公开岗位及对应详情；两个 POST 都是查询，不调用申请接口。"""
    result = {
        "status": "not_verified",
        "application_status": "not_tested",
        "feedback_status": "not_tested",
        "cooldown_status": "unknown",
        "evidence": [],
        "discovery_source": "https://s3.meituan.net/static-prod01/com.sankuai.recruitment.official.website/bundle-app_src_bootstrap_tsx-47c28d03.js",
    }

    def read_public(endpoint, payload):
        url = "https://zhaopin.meituan.com/api/official/job/" + endpoint
        evidence = {"url": url, "method": "POST", "request_body": payload, "observed_at": now_iso(), "authenticated": False}
        result["evidence"].append(evidence)
        resp = requests.post(url, json=payload, headers=HEADERS, timeout=TIMEOUT, allow_redirects=False)
        evidence.update({"status_code": resp.status_code, "final_url": resp.url, "body_sha256": hashlib.sha256(resp.content).hexdigest()})
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        if "json" not in resp.headers.get("Content-Type", "").lower():
            raise ValueError("non_json_response")
        body = resp.json()
        evidence["response_body"] = body
        if not isinstance(body, dict) or body.get("status") != 1:
            raise ValueError("business_status_not_success")
        if not isinstance(body.get("data"), dict):
            raise ValueError("unexpected_data_schema")
        return body["data"]

    try:
        listing = read_public("getJobList", {
            "page": {"pageNo": 1, "pageSize": 1}, "jobShareType": "1", "keywords": "",
            "cityList": [], "department": [], "jfJgList": [], "jobType": [], "typeCode": [],
        })
        jobs = listing.get("list")
        if not isinstance(jobs, list):
            raise ValueError("unexpected_list_schema")
        if not jobs:
            result["status"] = "no_jobs_returned"
            return result
        if not isinstance(jobs[0], dict) or not jobs[0].get("jobUnionId"):
            raise ValueError("missing_list_job_id")
        job_id = str(jobs[0]["jobUnionId"])
        detail = read_public("getJobDetail", {"jobUnionId": job_id, "jobShareType": "1"})
        if str(detail.get("jobUnionId")) != job_id:
            raise ValueError("job_id_mismatch")
        job = {
            "source_id": job_id,
            "title": detail.get("name"),
            "responsibilities": detail.get("jobDuty"),
            "requirements": detail.get("jobRequirement"),
            "source_url": "https://zhaopin.meituan.com/web/position/detail?" + urlencode({"jobUnionId": job_id, "jobShareType": "1"}),
            "source_refreshed_at": detail.get("refreshTime"),
            "locations": detail.get("cityList"),
            "recruitment_project": detail.get("projectName"),
        }
        result["job"] = job
        result["missing_fields"] = [key for key in ("title", "responsibilities", "requirements") if not isinstance(job[key], str) or not job[key].strip()]
        result["status"] = "incomplete_jd" if result["missing_fields"] else "jd_sample_obtained"
    except (requests.exceptions.RequestException, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return result


def probe_company(company: dict) -> dict:
    """探测一家企业招聘官网的首页和搜索页。"""
    name = company["name"]
    print(f"[公司] {name}")
    record = {
        "type": "company",
        "name": name,
        "career_home": fetch(company["career_home"]),
        "job_search": fetch(company["job_search"]),
    }
    if company["name"] == "美团" and company.get("public_job_sample"):
        record["job_sample"] = probe_meituan_public_job()
    return record


def probe_boss(config: dict) -> dict:
    """探测 BOSS 直聘公开搜索页。"""
    print("[平台] BOSS 直聘")
    record = {"type": "platform", "name": config["name"], "home": fetch(config["home"])}
    queries = config.get("sample_queries", [])
    search_results = []
    for q in queries[:2]:  # 限制探测数量，避免对站点造成压力
        keyword = q.get("keyword", "")
        city = q.get("city", "")
        query_url = config["job_search"]
        params = {}
        if keyword:
            params["query"] = keyword
        if city:
            params["city"] = city
        if params:
            query_url = f"{query_url}?{urlencode(params)}"
        res = fetch(query_url)
        res["query"] = q
        search_results.append(res)
    record["job_search_samples"] = search_results
    return record


def probe_liepin(config: dict) -> dict:
    """探测猎聘公开搜索页。"""
    print("[平台] 猎聘")
    record = {"type": "platform", "name": config["name"], "home": fetch(config["home"])}
    queries = config.get("sample_queries", [])
    search_results = []
    for q in queries[:2]:
        keyword = q.get("keyword", "")
        query_url = config["job_search"]
        if keyword:
            query_url = f"{query_url}?{urlencode({'key': keyword})}"
        res = fetch(query_url)
        res["query"] = q
        search_results.append(res)
    record["job_search_samples"] = search_results
    return record


def summarize(record: dict) -> dict:
    """为每条记录生成一句话可读摘要。"""
    def page_summary(page):
        if not page["ok"]:
            return page.get("error") or f"HTTP {page['status_code']}"
        states = {
            "verification_required": "HTTP 200；验证页（待人工核验）",
            "html_shell": "HTTP 200；页面壳，未取得正文",
            "empty_html": "HTTP 200；空 HTML",
            "non_html": "HTTP 200；非 HTML 响应",
            "html_content": "HTTP 200；有静态正文，JD 未验证",
        }
        return states.get(page.get("page_state"), "HTTP 200；内容未评估")

    if record["type"] == "company":
        home = record["career_home"]
        search = record["job_search"]
        home_summary = page_summary(home)
        search_summary = page_summary(search)
        sample_summary = ""
        if "job_sample" in record:
            sample_summary = f"；公开岗位样本：{record['job_sample']['status']}（不代表代投可用）"
        return {
            "name": record["name"],
            "home": home_summary,
            "search": search_summary,
            "detail": f"官网首页 {home_summary}，搜索页 {search_summary}{sample_summary}",
        }
    else:
        home = record["home"]
        home_summary = page_summary(home)
        samples_ok = sum(1 for s in record.get("job_search_samples", []) if s["ok"])
        total = len(record.get("job_search_samples", []))
        return {
            "name": record["name"],
            "home": home_summary,
            "search_samples_ok": f"{samples_ok}/{total}",
            "detail": f"首页 {home_summary}；样本仅 HTTP 200 数量 {samples_ok}/{total}，找岗未验证",
        }


def main():
    parser = argparse.ArgumentParser(description="只读公开页面探测；不验证或执行真实投递")
    parser.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "targets.yaml"))
    parser.add_argument("--companies", nargs="+", help="只探测指定公司名称")
    parser.add_argument("--skip-platforms", action="store_true", help="本轮不探测 BOSS 和猎聘")
    parser.add_argument("--meituan-job-sample", action="store_true", help="额外用公开查询 POST 读取美团列表中的一个岗位及详情；不提交申请")
    parser.add_argument("--output-dir", default=RESULTS_DIR)
    args = parser.parse_args()
    config_path = args.config
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    companies = config.get("companies", [])
    if args.companies:
        unknown = set(args.companies) - {c["name"] for c in companies}
        if unknown:
            parser.error("配置中没有公司：" + ", ".join(sorted(unknown)))
        companies = [c for c in companies if c["name"] in args.companies]
    if args.meituan_job_sample:
        if not any(c["name"] == "美团" for c in companies):
            parser.error("--meituan-job-sample 要求所选公司包含美团")
        companies = [{**c, "public_job_sample": c["name"] == "美团"} for c in companies]
    os.makedirs(args.output_dir, exist_ok=True)

    results = {
        "meta": {
            "purpose": "公开页面连通性探测",
            "run_at": now_iso(),
            "timeout_seconds": TIMEOUT,
            "disclaimer": "本脚本不登录、不投递、不读取私人消息；默认探测公开页面，可选读取一个美团公开岗位样本。",
            "method": "GET pages; optional public job query POSTs; no browser rendering, authentication or application submission",
            "meituan_job_sample_enabled": args.meituan_job_sample,
            "selected_companies": [c["name"] for c in companies],
        },
        "companies": [],
        "platforms": [],
    }

    for company in companies:
        results["companies"].append(probe_company(company))
        time.sleep(1)  # 礼貌间隔

    for platform_key in ([] if args.skip_platforms else ["boss", "liepin"]):
        platform_config = config.get("platforms", {}).get(platform_key)
        if not platform_config:
            continue
        if platform_key == "boss":
            results["platforms"].append(probe_boss(platform_config))
        else:
            results["platforms"].append(probe_liepin(platform_config))
        time.sleep(1)

    # JSON 报告
    json_path = os.path.join(args.output_dir, "probe_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Markdown 报告
    md_path = os.path.join(args.output_dir, "probe_report.md")
    lines = [
        "# 找岗与投递路径连通性探测报告",
        "",
        f"- 探测时间：{results['meta']['run_at']}",
        f"- 超时设置：{results['meta']['timeout_seconds']} 秒",
        f"- 说明：{results['meta']['disclaimer']}",
        "",
        "## 企业招聘官网",
        "",
        "| 公司 | 官网首页 | 招聘搜索页 | 摘要 |",
        "|------|----------|------------|------|",
    ]
    for record in results["companies"]:
        summary = summarize(record)
        home = record["career_home"]
        search = record["job_search"]
        lines.append(
            f"| {summary['name']} | "
            f"{home['status_code'] or home.get('error')} ({home['elapsed_ms']} ms) | "
            f"{search['status_code'] or search.get('error')} ({search['elapsed_ms']} ms) | "
            f"{summary['detail']} |"
        )

    lines += [
        "",
        "## BOSS 直聘 / 猎聘",
        "",
        "| 平台 | 首页 | 样本 HTTP 200 数量（非找岗成功） | 摘要 |",
        "|------|------|------------|------|",
    ]
    for record in results["platforms"]:
        summary = summarize(record)
        home = record["home"]
        lines.append(
            f"| {summary['name']} | "
            f"{home['status_code'] or home.get('error')} ({home['elapsed_ms']} ms) | "
            f"{summary['search_samples_ok']} | "
            f"{summary['detail']} |"
        )

    lines += [
        "",
        "## 注意事项",
        "",
        "1. **公开页面可达 ≠ 可自动获取完整 JD**：许多企业官网和招聘平台的完整岗位详情、投递入口需要登录或执行 JavaScript 才能渲染。",
        "2. **公开页面可达 ≠ 可代投**：真实投递需要处理登录、风控、表单、文件上传和回执核验。",
        "3. **反馈回收需单独授权**：站内消息、邮件、短信等反馈渠道涉及个人隐私，需要用户明确授权并验证平台接口或同步方式。",
        "4. **返回内容需核验**：HTTP 200 可能是空页面或验证页；脚本仅记录当前证据，不据此判断平台能否持续自动化。",
        "",
        "## 下一步建议",
        "",
        "- 首批企业样本已确认为阿里、腾讯、美团；细化业务板块和岗位后验证完整 JD。",
        "- 对需要登录的渠道，使用受控测试账号验证登录态维持、Cookie/Token 刷新和风控策略。",
        "- 对拟支持的反馈入口（如邮箱、BOSS 站内消息），分别做独立的小范围授权验证。",
        "- 对本地转写，使用实际面试录音样本在目标电脑上测量识别准确率与性能。",
    ]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n报告已保存：")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")


if __name__ == "__main__":
    main()
