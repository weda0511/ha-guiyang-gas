# 贵阳燃气（数联慧云）— Home Assistant 集成

把微信公众号「**贵阳燃气**」网上营业厅（数联慧云 `bc.shulianhuiyun.com`）的燃气账单接进 Home Assistant，生成 22 个传感器：欠费、当期燃气费、用气量、燃气表读数、账期、缴费状态、最新抄表读数、户名地址等。燃气表读数与用气量自带 `device_class: gas` + `state_class: total_increasing`，可直接接入 HA Energy 面板「燃气消耗」。

> English summary: A config-driven custom integration for Home Assistant that pulls gas billing data from the Guiyang Gas (Shulian Huiyun) WeChat H5 portal. Bring your own captured request headers; all URLs / headers / field mappings are configurable in the UI. Sister project of [ha-guiyang-water](https://github.com/weda0511/ha-guiyang-water). Chinese-only data source, so the rest of this README is in Chinese.

## 为什么需要抓包

贵阳燃气没有公开 API，数据只在公众号 H5 营业厅里。集成复用你一次抓包得到的登录态（token）来轮询三个只读查询接口。

经实测，这套接口的鉴权只需要 **3 个请求头**：`tenantId` / `tenantCode` / `token`：

- 不需要 Cookie（华为云 WAF 的 `HWWAFSESID` 等、`JSESSIONID` 都不用带）；
- 不需要微信 UA、Referer，任意 HTTP 客户端直连即可；
- 账单接口 `dateEnd` 可填 `20991231`，返回按账期升序，取最后一条即最新一期，一次配置永久滚动。

## ⚠️ 与水务集成的差异：token 有效期未知

水务那套的 `verfiy` 头是微信 openid，终身不变。**燃气这套是服务端签发的 token**（由微信 OAuth code 一次性换取，实测没有 refresh 接口），有效期未知（可能数天也可能数月）。集成已内置应对方案：

- token 失效时（HTTP 401/403 或返回「未授权」）自动进入**重新认证**流程，HA 会弹修复提示，在 UI 里重贴新 token 即可，无需删除重建；
- 重新抓包约 2 分钟：PC 微信打开「贵阳燃气」公众号 → 缴费/账单页，抓包后运行
  `python tools/gy_gas_probe.py 新抓包.har --replay --check` 即可一键验证并重生成配置。

## 传感器一览（22 个）

| 实体 | 说明 | 单位 | 来源接口 |
|:--|:--|:--|:--|
| `燃气欠费` | 欠费总额（opayAmt） | ¥ | getOpayAmt |
| `燃气账户余额` | cmAcctNum，后付费户一般为 0 | ¥ | getOpayAmt |
| `欠费-气费本金` | cmGasAmt | ¥ | getOpayAmt |
| `欠费-违约金` | cmLpcAmt | ¥ | getOpayAmt |
| `欠费-其他费用` | cmOtherAmt | ¥ | getOpayAmt |
| `计费日期` | amtDate | — | getOpayAmt |
| `当期燃气费` | 最新一期账单金额 | ¥ | getBillList |
| `当期用气量` | 本账期用气量（可进 Energy 面板） | m³ | getBillList |
| `燃气表读数` | 累计读数（可进 Energy 面板） | m³ | getBillList |
| `上期表读数` | — | m³ | getBillList |
| `账期起` / `账期止` | 如 20260920~20261020 | — | getBillList |
| `出账日` | billDttm | — | getBillList |
| `缴费状态` | 已缴费 / 未缴费（payoffFlg） | — | getBillList |
| `账单状态` | state（Y=有效） | — | getBillList |
| `最新抄表读数` | spInfoList.curBsegReading，比账单更及时 | m³ | userucuser/list |
| `最新抄表日` | curBsegDt | — | userucuser/list |
| `户名` / `用气地址` / `燃气表号` | 档案信息 | — | userucuser/list |
| `接口状态` / `最后更新` | 心跳 | — | — |

## 安装

### 方式一：HACS（自定义仓库）

1. HACS → 设置 → 添加自定义仓库，填本仓库地址，类别选 **集成**；
2. 搜索「贵阳燃气」安装；
3. 重启 Home Assistant。

### 方式二：手动

把 `custom_components/gy_gas/` 整个目录拷到 `<config>/custom_components/` 下，重启 Home Assistant。

## 使用步骤

### 1. 抓包（一次性，约 3 分钟）

PC 微信打开公众号「贵阳燃气」→ 缴费/账单查询，同时用 Fiddler / Charles 抓包导出 HAR。抓包里自然包含登录（authLoginUser）和三个查询请求，工具会自动识别。

> ⚠️ 只抓「查询」类页面，不要在缴费/提交表单页面操作。

### 2. 生成配置（先验证后信任）

```bash
python tools/gy_gas_probe.py 你的抓包.har            # 只解析, 生成 gy_gas_config.json
python tools/gy_gas_probe.py 你的抓包.har --replay    # 真实请求三个接口验证 + 字段树
python tools/gy_gas_probe.py 你的抓包.har --replay --check   # 只检查 token 是否有效
```

工具默认**不发任何请求**；`--replay` 才会真实请求并打印返回字段树，确认无误后生成 `gy_gas_config.json`。

### 3. 配置集成

设置 → 设备与服务 → 添加集成 → 搜索「贵阳燃气」，按 `gy_gas_config.json` 里的值填写：户号、三个接口 URL、请求头（3 个头的 JSON 文本）等，字段映射留空即用默认值。

### 4. token 失效怎么办

集成自动进入**重新认证**流程，在 UI 里重贴新抓包的请求头即可。也可用 `--check` 提前体检。

## 配置驱动：接口变了不用改代码

URL、请求头、数据根路径、字段映射全部可在集成「配置」页修改。字段映射支持三种前缀：

- 无前缀：取自账单主接口（root_path 下，默认 `data.bsegList.bseg[-1]` 即最新一期）；
- `@amt:` ：取自欠费接口 getOpayAmt；
- `@meter:`：取自抄表接口 userucuser/list。

若贵阳燃气以后改接口路径/字段名，大概率改配置就能救活，不用等发版。

## 隐私与安全

- `gy_gas_config.json` 与抓包文件（HAR/cURL）含 token、户号等登录态，**切勿提交到任何仓库或外传**（本仓库 `.gitignore` 已默认排除）；
- 本集成不接触任何缴费/支付接口，纯只读查询；
- 仓库内所有示例值均为占位符，不含任何真实用户数据。

## 免责声明

- 本项目为个人兴趣作品，与贵州燃气集团及数联慧云无任何关联；
- 接口为公众号 H5 私有接口，随时可能变动；请合理控制请求频率（默认 6 小时已足够），勿用于商业用途；
- 数据仅供对账参考，以燃气公司官方账单为准。

## 更新日志

- v0.1.0：初始版本（账单/欠费/抄表三接口，22 传感器，重新认证流程）。

## 致谢

- 姊妹项目 [weda0511/ha-guiyang-water](https://github.com/weda0511/ha-guiyang-water)（贵阳水务），本项目结构与工具链在其基础上适配燃气接口。

## License

MIT
