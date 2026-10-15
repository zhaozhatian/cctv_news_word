# 新闻联播文字版（T+1 电子档）

每天自动抓取**前一日**《新闻联播》的文字内容，生成一个纯静态阅读站点，可部署到任意静态服务器（nginx / Apache / phpStudy / 对象存储静态托管均可），实现 T+1 新闻联播内容查看。

**仅依赖 Python 3.8+ 标准库，无需 pip install 任何东西。**

## 数据链路（全部为央视网公开页面/接口，低频访问）

```
① 单日节目单   https://tv.cctv.com/lm/xwlb/day/YYYYMMDD.shtml
      │        （当期完整版 + 全部条目的标题、时长、详情页链接）
      ▼
② 每条新闻详情页  https://tv.cctv.com/…/VIDExxxxx.shtml
      │        （提取 var guid = "xxx" 与 <div id="content_area"> 正文文字）
      ▼
③ 视频信息接口   https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid=<完整版guid>
               （补充标题、栏目、播出时间 f_pgmtime、时长等元数据）
```

产出：`site/data/YYYY-MM-DD.json`（每日数据）+ `site/data/index.json`（期次索引），
由 `site/index.html` + `assets/app.js` 在浏览器端渲染成阅读页。

## 快速开始

```bash
cd xwlb

python xwlb.py fetch                # 抓取前一日（T+1）
python xwlb.py fetch --date 2026-10-14        # 抓取指定日期
python xwlb.py backfill --days 30   # 回补最近 30 天（已有的自动跳过）
python xwlb.py backfill --from 2026-10-01 --to 2026-10-14
python xwlb.py schedule             # 内置定时器：每天 08:00 抓前一日
```

抓取一天约 17 个请求、耗时 15 秒左右。抓完后用浏览器通过 **HTTP** 访问 `site/` 目录即可，
例如 phpStudy 环境下项目放在 `D:\phpstudy_pro\WWW\xwlb`，则访问：

```
http://localhost/xwlb/site/
```

> 注意：不要直接双击 `index.html`（file:// 协议下浏览器禁止 fetch 本地 JSON，页面会提示错误）。
> 临时预览也可以用：`python -m http.server 8000 --directory site`

## 部署到服务器

把 **`site/` 目录整个上传**到 Web 根目录即可（纯静态，无需任何后端）。以后每天定时任务跑完后，
把 `site/data/` 同步上去即可；`index.html` 与 `assets/` 不会变化。

同步示例（Linux，rsync）：

```bash
rsync -av --delete site/ user@server:/var/www/xwlb/
```

## 定时执行（三选一）

### 方式一：内置定时器（最简单，跨平台）

```bash
python xwlb.py schedule            # 每天 08:00 抓前一日，失败自动重试
python xwlb.py schedule --time 07:30
```

- 日志同时写入 `xwlb.log`；
- 页面未发布/网络抖动时按 `retry_wait_minutes` 间隔重试 `retries` 次；
- 挂后台：Windows 可用 `start /min python xwlb.py schedule`，Linux 可配合 `nohup` 或 systemd。

### 方式二：Windows 计划任务

管理员 cmd 执行（按实际 Python 路径调整）：

```bat
schtasks /Create /TN "xwlb-t1" /TR "\"C:\Path\to\python.exe\" \"D:\phpstudy_pro\WWW\xwlb\xwlb.py\" fetch" /SC DAILY /ST 08:00
```

### 方式三：Linux crontab

```cron
0 8 * * * cd /path/to/xwlb && /usr/bin/python3 xwlb.py fetch >> cron.log 2>&1
```

## 配置（config.json）

| 字段 | 默认 | 说明 |
|---|---|---|
| `output_dir` | `site` | 静态站点输出目录（相对脚本目录，可绝对路径） |
| `schedule_time` | `08:00` | schedule 模式每日执行时间 |
| `retries` | `8` | schedule 模式失败重试次数 |
| `retry_wait_minutes` | `10` | schedule 模式重试间隔 |
| `request_delay_seconds` | `0.6` | 相邻请求间隔（请勿调得太小，保持礼貌抓取） |
| `http_timeout_seconds` | `20` | 单次请求超时 |

## 目录结构

```
xwlb/
├── xwlb.py              # 主程序（fetch / backfill / schedule）
├── config.json          # 可选配置
├── template/            # 静态页模板（每次抓取自动同步到输出目录）
│   ├── index.html
│   └── assets/{style.css, app.js}
├── xwlb.log             # schedule 模式运行日志
└── site/                # ★ 部署这个目录
    ├── index.html
    ├── assets/
    └── data/
        ├── index.json           # 期次索引（页面日期下拉框数据源）
        └── 2026-10-14.json      # 每日数据（标题/时长/播出时间/各条正文）
```

## 页面功能

- **内嵌视频播放**：每条新闻「▶ 播放本条」、每期「▶ 播放完整版」均可直接在页面内播放。
  播放时前端实时调用 `getHttpVideoInfo.do`（该接口 CORS 全开）获取**最新不过期**的 mp4 分段地址，
  数据文件只存 guid；完整版多分段自动连播。视频地址若失效会提示并给出官方页面链接。
- 日期下拉框 / 「前一天」「后一天」按钮 / 键盘 ← → 翻期，URL hash 可深链（如 `#2026-10-14`）
- 每期元信息：播出时间、时长、条数、官方页面链接（跳转央视网）
- 本期目录（锚点跳转）、正文段落首行缩进、`央视网消息` 导语加粗
- 自动适配深色模式；「打印 / PDF」按钮输出干净的打印排版（自动隐藏播放器）
- 每条新闻保留 guid 与原文链接，便于溯源

## 合规说明

- 仅请求央视网公开页面与公开接口，单日约 17 个请求，带 User-Agent 与 Referer，请求间隔 0.6 秒；
- 内容版权归中央广播电视总台所有，本项目仅供个人学习研究使用，请勿公开传播抓取内容或用于商业用途；
- 请勿高频抓取或绕过访问限制，保持 `request_delay_seconds` 的默认值。
