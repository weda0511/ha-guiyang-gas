# -*- coding: utf-8 -*-
"""贵阳燃气(数联慧云) 集成 - 常量定义."""
DOMAIN = "gy_gas"
DEFAULT_NAME = "贵阳燃气"
DEFAULT_SCAN_INTERVAL = 21600  # 6 小时; 燃气一月一出账, 24h 也够

# config entry 字段
CONF_ACCT_ID = "acct_id"
CONF_METHOD = "method"
CONF_URL = "url"                  # 主接口: 账单列表 getBillList
CONF_AMT_URL = "amt_url"          # 辅接口 1: 欠费/余额 getOpayAmt
CONF_METER_URL = "meter_url"      # 辅接口 2: 抄表读数 userucuser/list
CONF_HEADERS = "headers"          # JSON 文本: {"tenantId":..,"tenantCode":..,"token":..}
CONF_BODY = "body"                # 请求体模板, 支持 {acct_id} 占位符
CONF_ROOT_PATH = "root_path"      # 账单主接口里数据对象路径
CONF_FIELD_MAP = "field_map"      # JSON 文本: 标准字段 -> 返回字段点路径
CONF_SCAN_INTERVAL = "scan_interval"

# 字段映射前缀: 指明该字段取自哪个接口响应
PREFIX_AMT = "@amt:"              # 欠费接口(getOpayAmt)
PREFIX_METER = "@meter:"          # 抄表接口(userucuser/list)
# 无前缀 = 主接口(账单列表)root_path 下取值; 取不到再从主接口响应根部找

# ---- 标准字段(传感器) ----
# 来自账单主接口(默认 root_path = data.bsegList.bseg[-1], 即最新一期账单)
STD_BILL_AMT = "bill_amt"         # 当期账单金额
STD_USAGE = "usage"               # 当期用气量
STD_READING = "reading"           # 当期抄表读数(累计)
STD_LAST_READING = "last_reading"  # 上期抄表读数
STD_PERIOD_START = "period_start"  # 账期起
STD_PERIOD_END = "period_end"     # 账期止
STD_BILL_DATE = "bill_date"       # 出账日
STD_PAYOFF = "payoff"             # 缴费状态(Y/N)
STD_BILL_STATE = "bill_state"     # 账单状态
# 来自欠费接口
STD_DUE = "due"                   # 欠费总额
STD_GAS_FEE = "gas_fee"           # 欠费-气费本金
STD_LATE_FEE = "late_fee"         # 欠费-违约金
STD_OTHER_FEE = "other_fee"       # 欠费-其他费用
STD_BALANCE = "balance"           # 账户余额(cmAcctNum)
STD_AMT_DATE = "amt_date"         # 计费日期
# 来自抄表接口
STD_CUR_READING = "cur_reading"   # 最新抄表读数
STD_CUR_READ_DATE = "cur_read_date"  # 最新抄表日
STD_USER_NAME = "user_name"       # 户名
STD_ADDRESS = "address"           # 用气地址
STD_METER_NO = "meter_no"         # 燃气表表号
# 系统
STD_STATUS = "status"             # 接口状态: ok / error
STD_UPDATED = "updated"           # 最后成功更新时间

DEFAULT_ROOT_PATH = "data.bsegList.bseg[-1]"

DEFAULT_FIELD_MAP = {
    STD_BILL_AMT: "bsegAmt",
    STD_USAGE: "mtrList[0].bsegQty",
    STD_READING: "mtrList[0].endBsegReading",
    STD_LAST_READING: "mtrList[0].startBsegReading",
    STD_PERIOD_START: "startDate",
    STD_PERIOD_END: "endDate",
    STD_BILL_DATE: "billDttm",
    STD_PAYOFF: "payoffFlg",
    STD_BILL_STATE: "state",
    STD_DUE: PREFIX_AMT + "data.opayAmt",
    STD_GAS_FEE: PREFIX_AMT + "data.cmGasAmt",
    STD_LATE_FEE: PREFIX_AMT + "data.cmLpcAmt",
    STD_OTHER_FEE: PREFIX_AMT + "data.cmOtherAmt",
    STD_BALANCE: PREFIX_AMT + "data.cmAcctNum",
    STD_AMT_DATE: PREFIX_AMT + "data.amtDate",
    STD_CUR_READING: PREFIX_METER + "rows[0].spInfoList[0].curBsegReading",
    STD_CUR_READ_DATE: PREFIX_METER + "rows[0].spInfoList[0].curBsegDt",
    STD_USER_NAME: PREFIX_METER + "rows[0].userName",
    STD_ADDRESS: PREFIX_METER + "rows[0].gasAddress",
    STD_METER_NO: PREFIX_METER + "rows[0].gasMeterNumber",
}

# 缴费状态原始值 -> 中文
PAYOFF_MAP = {"Y": "已缴费", "N": "未缴费"}

# 返回体里出现这些关键字视为登录态失效(即使 HTTP 200)
AUTH_FAIL_KEYWORDS = ("未登录", "请登录", "登录失效", "登录已过期", "token失效", "token过期",
                      "未授权", "请先绑定", "unauthorized", "not login")
