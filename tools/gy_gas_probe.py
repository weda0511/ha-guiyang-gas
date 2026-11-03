# -*- coding: utf-8 -*-
"""贵阳燃气(数联慧云 hallapp) —— 公众号 H5 抓包验证/配置生成工具

用途:
  1) 解析 Charles / Fiddler 导出的 .har(或复制的 cURL), 自动识别燃气三件套接口:
       - 账单列表 getBillList      -> 主接口
       - 欠费/余额 getOpayAmt      -> 辅接口 1
       - 抄表读数 userucuser/list  -> 辅接口 2
     并从登录响应里提取 tenantId / tenantCode / token / ucUserId(openid) / acctId;
  2) 加 --replay 时真实请求一次(只读查询), 打印返回 JSON 字段树;
  3) 生成 gy_gas_config.json, 供 custom_components/gy_gas 集成直接填用。

安全约定:
  * 默认只解析, 不发任何网络请求; 加 --replay 才重放;
  * 只重放 GET 查询接口, 工具会拒绝重放 authLoginUser(POST 登录)等写操作接口;
  * token / openid 在屏幕日志中脱敏, 但明文写入 gy_gas_config.json(集成需要), 勿外传、勿提交 git。

用法:
  python gy_gas_probe.py capture.har --list              # 列出接口请求清单
  python gy_gas_probe.py capture.har                     # 只解析并生成配置骨架
  python gy_gas_probe.py capture.har --replay            # 重放三个查询接口验证 + 打印字段树
  python gy_gas_probe.py capture.har --replay --check    # 只验证 token 是否还有效
  python gy_gas_probe.py --demo                          # 离线演示, 不发任何请求
"""
import argparse
import io
import json
import os
import re
import shlex
import sys
import urllib.request
import urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SENSITIVE_KEYS = ("token", "cookie", "authorization", "openid", "ucuserid", "session")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gy_gas_config.json")

# 三个查询接口的 URL 特征(按优先级.)
PATTERNS = {
    "bill": ("customerbilling/getBillList",),
    "amt": ("customerbilling/getOpayAmt",),
    "meter": ("userucuser/list",),
    "login": ("token/authLoginUser",),
}

DEFAULT_FIELD_MAP = {
    "bill_amt": "bsegAmt",
    "usage": "mtrList[0].bsegQty",
    "reading": "mtrList[0].endBsegReading",
    "last_reading": "mtrList[0].startBsegReading",
    "period_start": "startDate",
    "period_end": "endDate",
    "bill_date": "billDttm",
    "payoff": "payoffFlg",
    "bill_state": "state",
    "due": "@amt:data.opayAmt",
    "gas_fee": "@amt:data.cmGasAmt",
    "late_fee": "@amt:data.cmLpcAmt",
    "other_fee": "@amt:data.cmOtherAmt",
    "balance": "@amt:data.cmAcctNum",
    "amt_date": "@amt:data.amtDate",
    "cur_reading": "@meter:rows[0].spInfoList[0].curBsegReading",
    "cur_read_date": "@meter:rows[0].spInfoList[0].curBsegDt",
    "user_name": "@meter:rows[0].userName",
    "address": "@meter:rows[0].gasAddress",
    "meter_no": "@meter:rows[0].gasMeterNumber",
}

DEMO_CURL = r"""curl 'https://bc.shulianhuiyun.com/business-hall-admin/user/customerbilling/getBillList?dateStart=20240101&dateEnd=20991231&acctId=0000000000' \
  -H 'tenantId: 1549700407420260355' \
  -H 'tenantCode: 10000001' \
  -H 'token: demo-token'"""
DEMO_RESPONSE = {"msg": "success", "code": 0, "data": {
    "acctId": "0000000000", "entityName": "*某某", "address": "示例地址",
    "opayAmt": "0", "badgeNbr": "0000",
    "bsegList": {"bseg": [{
        "billDttm": "20261023", "startDate": "20260920", "endDate": "20261020",
        "bsegAmt": "36.00", "state": "Y", "payoffFlg": "Y",
        "mtrList": [{"startBsegReading": "770.00", "endBsegReading": "782.00", "bsegQty": "12.00"}],
        "linesList": [{"lineDes": "一阶梯气费12(立方)X￥3.00", "lineAmt": "36.00"}]}]}}}


def log(stage, msg):
    print("[%s] %s" % (stage, msg))


def mask(v):
    s = str(v)
    if len(s) <= 12:
        return "***"
    return s[:6] + "..." + s[-4:]


def is_sensitive(k):
    kl = str(k).lower()
    return any(s in kl for s in SENSITIVE_KEYS)


def parse_curl(text):
    """把 cURL 命令文本解析成 {method,url,headers,body}"""
    text = text.replace("\\\r\n", " ").replace("\\\n", " ").strip()
    if not text.lower().lstrip().startswith("curl"):
        raise ValueError("文件内容不是 cURL 命令(应以 curl 开头)")
    tokens = shlex.split(text)
    url, method, headers, body = "", None, {}, ""
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t in ("-X", "--request"):
            method = tokens[i + 1]; i += 2
        elif t in ("-H", "--header"):
            kv = tokens[i + 1]
            if ":" in kv:
                k, v = kv.split(":", 1)
                headers[k.strip()] = v.strip()
            i += 2
        elif t in ("-b", "--cookie", "-A", "--user-agent"):
            headers["Cookie" if t in ("-b", "--cookie") else "User-Agent"] = tokens[i + 1]; i += 2
        elif t in ("-d", "--data", "--data-raw", "--data-binary"):
            body = tokens[i + 1]; i += 2
        elif t.startswith("-"):
            i += 1
        else:
            url = t; i += 1
    if not url:
        raise ValueError("未从 cURL 中解析到 URL")
    return {"method": (method or ("POST" if body else "GET")).upper(),
            "url": url, "headers": headers, "body": body}


def har_entries(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        har = json.load(f)
    return har.get("log", {}).get("entries", [])


def entry_to_req(e):
    req = e.get("request", {})
    headers = {h["name"]: h["value"] for h in req.get("headers", [])}
    body = (req.get("postData") or {}).get("text", "")
    return {"method": req.get("method", "GET").upper(), "url": req.get("url", ""),
            "headers": headers, "body": body}


def resp_text(e):
    c = e.get("response", {}).get("content", {})
    t = c.get("text", "") or ""
    if c.get("encoding") == "base64" and t:
        import base64
        try:
            t = base64.b64decode(t).decode("utf-8", "replace")
        except Exception:
            t = ""
    return t


def classify(url):
    for kind, pats in PATTERNS.items():
        for p in pats:
            if p in url:
                return kind
    return None


def scan_har(entries):
    """扫描 HAR, 提取三接口 URL + 登录态 + 户号"""
    found = {}
    for e in entries:
        req = e.get("request", {})
        url = req.get("url", "")
        kind = classify(url)
        if not kind:
            continue
        item = entry_to_req(e)
        item["response"] = resp_text(e)
        item["index"] = entries.index(e)
        # 同名取"信息量最大"的一条: meter 优先带 flag=true, bill/amt 取最后一条
        if kind == "meter":
            if kind not in found or "flag=true" in url:
                found[kind] = item
        else:
            if kind not in found or len(item["response"]) >= len(found[kind]["response"]):
                found[kind] = item
    return found


def extract_creds(found):
    """从登录响应取 token/tenant, 从接口响应取 acctId/ucUserId"""
    creds = {"tenant_id": "", "tenant_code": "", "token": "", "acct_id": "", "uc_user_id": ""}
    login = found.get("login")
    if login:
        hdrs = {k.lower(): v for k, v in login["headers"].items()}
        creds["tenant_id"] = hdrs.get("tenantid", "")
        creds["tenant_code"] = hdrs.get("tenantcode", "")
        try:
            data = json.loads(login["response"])
            d = (data.get("data") or {})
            creds["token"] = d.get("token") or ""
            auth = (d.get("authData") or {}).get("data") or {}
            creds["uc_user_id"] = auth.get("openid") or ""
        except (ValueError, AttributeError):
            pass
    for kind in ("bill", "amt", "meter"):
        it = found.get(kind)
        if not it:
            continue
        hdrs = {k.lower(): v for k, v in it["headers"].items()}
        creds["tenant_id"] = creds["tenant_id"] or hdrs.get("tenantid", "")
        creds["tenant_code"] = creds["tenant_code"] or hdrs.get("tenantcode", "")
        creds["token"] = creds["token"] or hdrs.get("token", "")
        m = re.search(r"acctId=([^&]+)", it["url"])
        if m:
            creds["acct_id"] = m.group(1)
        m = re.search(r"ucUserId=([^&]+)", it["url"])
        if m:
            creds["uc_user_id"] = m.group(1)
    return creds


def normalize_bill_url(url):
    """账单接口日期范围放宽: dateEnd=20991231, dateStart 缺省补 20240101"""
    if "getBillList" not in url:
        return url
    if "dateEnd=" in url:
        url = re.sub(r"dateEnd=\d+", "dateEnd=20991231", url)
    else:
        url += ("&" if "?" in url else "?") + "dateEnd=20991231"
    if "dateStart=" not in url:
        url += "&dateStart=20240101"
    return url


def normalize_meter_url(url, uc_user_id):
    if "userucuser/list" not in url:
        return url
    if "flag=true" not in url:
        url += "&flag=true"
    if "gasUserNumber=" not in url:
        url += "&gasUserNumber="
    return url


def field_tree(obj, prefix="$", depth=0, out=None, limit=6):
    if out is None:
        out = []
    if depth > limit:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = "%s.%s" % (prefix, k)
            if isinstance(v, (dict, list)):
                field_tree(v, p, depth + 1, out, limit)
            else:
                s = str(v)
                if len(s) > 40:
                    s = s[:37] + "..."
                out.append("%-52s = %-22s (%s)" % (p, s, type(v).__name__))
    elif isinstance(obj, list):
        for n, v in enumerate(obj[:2]):
            field_tree(v, "%s[%d]" % (prefix, n), depth + 1, out, limit)
        if len(obj) > 2:
            out.append("%s[...]  共 %d 项" % (prefix, len(obj)))
    return out


def replay(url, headers, timeout=20):
    r = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        if k.lower() in ("host", "content-length", "accept-encoding", "cookie"):
            continue
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return "ERR", repr(e)[:200]


def gen_config(creds, bill_url, amt_url, meter_url, acct_id):
    cfg = {
        "_说明": "运行 tools/gy_gas_probe.py 自动生成; 含登录 token, 切勿提交仓库或外传",
        "acct_id": acct_id or creds.get("acct_id", ""),
        "method": "GET",
        "url": bill_url,
        "amt_url": amt_url,
        "meter_url": meter_url,
        "headers": {
            "tenantId": creds.get("tenant_id", ""),
            "tenantCode": creds.get("tenant_code", ""),
            "token": creds.get("token", ""),
        },
        "body": "",
        "root_path": "data.bsegList.bseg[-1]",
        "field_map": dict(DEFAULT_FIELD_MAP),
        "scan_interval": 21600,
        "_字段前缀说明": "@amt: 取自欠费接口 getOpayAmt; @meter: 取自抄表接口 userucuser/list",
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def main():
    ap = argparse.ArgumentParser(description="贵阳燃气(数联慧云) 抓包验证工具")
    ap.add_argument("capture", nargs="?", help="cURL 文本文件或 .har 文件")
    ap.add_argument("--replay", action="store_true", help="真实请求一次三个查询接口(默认只解析)")
    ap.add_argument("--check", action="store_true", help="配合 --replay: 只验证 token 是否有效")
    ap.add_argument("--list", action="store_true", help="HAR 模式: 列出接口请求清单")
    ap.add_argument("--entry", type=int, default=-1, help="HAR 模式: 只解析指定序号的请求")
    ap.add_argument("--acct-id", default="", help="燃气户号(acctId), 缺省自动从抓包提取")
    ap.add_argument("--demo", action="store_true", help="离线演示")
    args = ap.parse_args()

    if args.list:
        if not args.capture or not args.capture.lower().endswith(".har"):
            ap.error("--list 仅支持 .har 文件")
        entries = har_entries(args.capture)
        print("共 %d 条请求, 接口类如下:" % len(entries))
        for n, e in enumerate(entries):
            req = e.get("request", {})
            url = req.get("url", "")
            if re.search(r"\.(js|css|png|jpg|jpeg|woff2?|svg|ico)(\?|$)", url):
                continue
            size = e.get("response", {}).get("content", {}).get("size", 0)
            tag = classify(url) or "-"
            print("  [%02d] %-6s %-4s %s (%d bytes)" % (n, tag, req.get("method"), url[:110], size))
        print("提示: 用 --entry <序号> 可单独解析某条(一般不需要, 工具会自动识别三件套)")
        return

    if args.demo:
        log("1/5", "演示模式(离线, 不发请求)")
        req = parse_curl(DEMO_CURL)
        creds = {"tenant_id": "1549700407420260355", "tenant_code": "10000001", "token": "demo-token"}
        bill_url, amt_url, meter_url, acct_id = req["url"], "", "", "0000000000"
    elif args.capture:
        ext = os.path.splitext(args.capture)[1].lower()
        log("1/5", "读取抓包文件: %s (%s)" % (args.capture, "HAR" if ext == ".har" else "cURL"))
        if ext == ".har":
            entries = har_entries(args.capture)
            if not entries:
                ap.error("HAR 中没有请求记录")
            if args.entry >= 0:
                req = entry_to_req(entries[args.entry])
                creds = {k: "" for k in ("tenant_id", "tenant_code", "token", "acct_id", "uc_user_id")}
                h = {k.lower(): v for k, v in req["headers"].items()}
                creds.update({"tenant_id": h.get("tenantid", ""), "tenant_code": h.get("tenantcode", ""),
                              "token": h.get("token", "")})
                m = re.search(r"acctId=([^&]+)", req["url"])
                acct_id = m.group(1) if m else ""
                bill_url = normalize_bill_url(req["url"])
                amt_url = meter_url = ""
                log("1/5", "使用指定条目 [%02d]" % args.entry)
            else:
                found = scan_har(entries)
                if "bill" not in found and "amt" not in found:
                    ap.error("未在抓包里找到燃气账单接口(customerbilling/getBillList 或 getOpayAmt)。"
                             "请确认抓的是「燃气缴费/账单查询」页面, 或先用 --list 看看抓到了什么")
                creds = extract_creds(found)
                acct_id = args.acct_id or creds.get("acct_id", "")
                bill_url = normalize_bill_url(found["bill"]["url"]) if "bill" in found else ""
                amt_url = found["amt"]["url"] if "amt" in found else ""
                meter_url = normalize_meter_url(found["meter"]["url"], creds.get("uc_user_id", "")) \
                    if "meter" in found else ""
                log("1/5", "识别结果: 账单=%s 欠费=%s 抄表=%s" % (
                    "有" if bill_url else "无", "有" if amt_url else "无", "有" if meter_url else "无"))
        else:
            with open(args.capture, encoding="utf-8", errors="replace") as f:
                req = parse_curl(f.read())
            h = {k.lower(): v for k, v in req["headers"].items()}
            creds = {"tenant_id": h.get("tenantid", ""), "tenant_code": h.get("tenantcode", ""),
                     "token": h.get("token", ""), "acct_id": "", "uc_user_id": ""}
            m = re.search(r"acctId=([^&]+)", req["url"])
            acct_id = args.acct_id or (m.group(1) if m else "")
            bill_url = normalize_bill_url(req["url"])
            amt_url = meter_url = ""
    else:
        ap.error("请提供抓包文件, 或使用 --demo")
        return

    headers = {"tenantId": creds.get("tenant_id", ""), "tenantCode": creds.get("tenant_code", ""),
               "token": creds.get("token", ""), "Accept": "application/json"}

    log("2/5", "提取到的登录态与户号:")
    print("      tenantId   : %s" % (creds.get("tenant_id") or "(未识别)"))
    print("      tenantCode : %s" % (creds.get("tenant_code") or "(未识别)"))
    print("      token      : %s" % (mask(creds.get("token")) if creds.get("token") else "(未识别)"))
    print("      acctId     : %s" % (acct_id or "(未识别, 用 --acct-id 指定)"))
    print("      ucUserId   : %s" % (mask(creds.get("uc_user_id")) if creds.get("uc_user_id") else "(未识别)"))
    print("      账单 URL   : %s" % (bill_url[:110] or "(无)"))
    print("      欠费 URL   : %s" % (amt_url[:110] or "(无)"))
    print("      抄表 URL   : %s" % (meter_url[:110] or "(无)"))

    if not creds.get("token") or not creds.get("tenant_id"):
        log("3/5", "⚠ 未识别到完整登录态(token/tenantId)。请确认抓包包含 /user/token/authLoginUser 登录请求;"
                   "若只有单条接口 cURL, 请手工补齐 token")
    elif args.replay:
        log("3/5", "重放查询接口(只读 GET, 超时 20s)...")
        ok = True
        if args.check:
            st, txt = replay(amt_url or bill_url, headers)
            alive = st == 200 and '"code":0' in txt.replace(" ", "")
            print("      token 检查: HTTP %s -> %s" % (st, "有效 ✅" if alive else "已失效 ❌ 需重新抓包"))
            return
        for name, url in (("账单", bill_url), ("欠费", amt_url), ("抄表", meter_url)):
            if not url:
                print("      [%s] 跳过(抓包中未出现)" % name)
                continue
            st, txt = replay(url, headers)
            print("      [%s] HTTP %s" % (name, st))
            if st != 200:
                ok = False
                print("           %s" % txt[:200])
                continue
            try:
                tree = field_tree(json.loads(txt))
            except ValueError:
                print("           (返回不是 JSON) %s" % txt[:200])
                continue
            for line in tree[:28]:
                print("           %s" % line)
            if len(tree) > 28:
                print("           ... 其余 %d 行省略" % (len(tree) - 28))
        log("4/5", "重放%s" % ("成功" if ok else "存在问题(见上)"))
    else:
        log("3/5", "未加 --replay, 不发网络请求")
        log("4/5", "跳过字段树")

    cfg = gen_config(creds, bill_url, amt_url, meter_url, acct_id)
    log("5/5", "已生成集成配置: %s" % CONFIG_FILE)
    if args.replay:
        print("      下一步: 按该文件的 7 项填进 HA 集成「贵阳燃气」配置页")
    else:
        print("      下一步: python gy_gas_probe.py %s --replay   # 验证接口并打印字段" % args.capture)


if __name__ == "__main__":
    main()
