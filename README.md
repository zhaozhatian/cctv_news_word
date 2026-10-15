# 新闻联播文字版（T+1）

每天自动抓取前一日央视网《新闻联播》的文字内容，生成纯静态阅读站（支持内嵌播放视频）。
仅依赖 Python 3.8+ 标准库，无需安装第三方包。

## 使用

```bash
python xwlb.py fetch                  # 抓取前一日（T+1）
python xwlb.py fetch --date 2026-10-14
python xwlb.py backfill --days 30     # 回补历史（已存在的跳过）
python xwlb.py schedule               # 每天 08:00 自动抓前一日，失败自动重试
```

抓取完成后通过 HTTP 访问 `site/` 目录即可（如 `http://localhost/xwlb/site/`），
不要直接双击 index.html。部署时把 `site/` 整个上传到任意静态服务器即可；
定时任务也可以用 crontab / Windows 计划任务直接调 `python xwlb.py fetch`。

## 配置

可选的 `config.json`（缺省时用默认值），各字段：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `output_dir` | `site` | 静态站点输出目录（相对脚本目录，可绝对路径） |
| `schedule_time` | `08:00` | schedule 模式每天执行时间（也可用 `--time` 覆盖） |
| `retries` | `8` | schedule 模式失败重试次数 |
| `retry_wait_minutes` | `10` | schedule 模式重试间隔（分钟） |
| `request_delay_seconds` | `0.6` | 相邻请求间隔秒数，请保持勿调小 |
| `http_timeout_seconds` | `20` | 单次请求超时 |

## 数据来源

均为央视网公开页面与接口：单日节目单 `tv.cctv.com/lm/xwlb/day/YYYYMMDD.shtml`
→ 每条新闻详情页（正文文字 + guid）→ `getHttpVideoInfo.do`（元数据）。
页面播放视频时由前端实时调用该接口获取最新地址。

内容版权归中央广播电视总台所有，仅供个人学习研究，请勿公开传播或用于商业用途。
