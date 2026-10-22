# 共同操作、输入与交付

## 任务边界

开始时确定：平台 URL、组织、资源类型、目标（新建或现有 ID）、预期结果（保存草稿/发布/下架/删除/实际执行）、允许的使用范围。已有会话明确给出的选择继续沿用。多候选名称、缺失平台或成员 UUID 等会影响落点时询问；不用随机选第一项。

参数示例中的 `<ORG_UUID>`、`<ID>`、`<REVISION>` 等必须替换为查询结果，不要原样粘贴运行。示例域名保留给说明，不是可用服务器。POSIX shell 可设置 `ACTVERO_SERVER`、`ACTVERO_ORG` 变量简化参数，但 **CLI 不自动读取它们**，必须继续传 `--server "$ACTVERO_SERVER" --org "$ACTVERO_ORG"`。

## 输出和分页

成功 stdout 是 JSON，`--json` 仅压缩为一行；`--help` 是普通文本。失败退出非零，stderr 最后一个错误对象为 `{"error":{"code","message","status"?,"request_id"?}}`。写入前 stderr 还会打印中文请求编号，不能把整个 stderr 当一个 JSON 对象。不要因为 stdout 文件存在就认定成功；先检查退出状态再解析。

资源响应通常为：

```json
{
  "organization": {"org_id": "目标组织 UUID", "name": "目标组织"},
  "result": {},
  "request_id": "写操作编号，部分读取没有此项"
}
```

以上是结构说明，organization 实际还含权限等字段。检查 `organization.org_id` 等于目标。列表通常位于 `result.items`，分页有 `total/page`（有些含 page_size），用实际返回条数累计，不假定固定页长。组织列表直接顶层 items；MCP 服务列表不分页；分类 result 直接是数组。

## 输入文件与并发

CLI 的 `--file`/`--metadata` 读取 UTF-8 JSON 对象，最大 5 MB；不接受 YAML、数组、带注释 JSON 或标准输入 `-`。按 `schema show <SchemaName>` 选择可写字段，JSON Schema 的格式约束只是形状；跨字段、权限、外部可达性、依赖状态仍由服务端验证。

写入前读取最新详情，使用当前 `revision`（Skills/专家/分类）或 `version`（MCP 服务）。这些是正整数并发修订号，与发布版本 `1.0.0`、版本 UUID 完全不同。不要自行 +1，不用上一次任务缓存的值。每次写完重新读取，下一次使用新响应值。

完整更新需要保留未改字段。Skills 保留 display_name/description/audience/member_ids；专家保留完整 content 与 category ID；MCP 服务按 McpServiceUpdate 可写字段投影保留原配置。不要提交 view 字段或把缺省数组当作“保持不变”。

只含假域名、无凭据的示例可保存到项目；真实配置、响应、授权 URL、MCP 参数结果等按用户数据要求放私有临时目录。不要写入公开仓库、npm 包、聊天或开发过程文档。

## 写操作编号和未知结果

需要确定性恢复的写入，先生成 UUID，传 `--request-id`，将原请求文件和编号私有保存；默认 CLI 也会自动生成并在发送前登记。Node 可生成：

```sh
node -e "process.stdout.write(require('node:crypto').randomUUID())"
actvero commands show <REQUEST_UUID> --server <SERVER> --org <ORG_UUID> --json
```

回执在 `result`：`status=pending|succeeded|unknown`。succeeded 通常含原完整响应 `result.result`，即里面再有 organization/result；不要误取成资源本体。MCP run/OAuth start 仅保存状态、不保留内容，结果标记 `result_retained: false`。

同编号重放只适用于同组织、同用户、相同方法/路径/原始正文、原操作已成功且保留结果。不要修订文件后用旧编号。pending/unknown 或结果缺失时先核对资源和活动，不创建新编号盲目重发。完整处置见 [恢复](recovery.md)。

## 使用范围与依赖

Skills/专家：`administrators`、`selected`、`organization`；selected 必须有组织 membership UUID，其他范围 member_ids 必须空。

MCP：`selected` 或 `organization`，selected 空列表可以表达尚未向指定成员开放；没有 administrators 值。服务启用、工具策略、凭据可用、成员范围是独立条件，分别检查。

当前 CLI 只能列出组织及自己的 membership_id，没有完整组织成员管理/搜索。需要其他成员 ID 时由用户提供或在后台获取；不把用户账号 UUID当成员 ID，不为避开缺失信息扩大范围。

## 完成条件

| 操作 | 至少核验 |
| --- | --- |
| 新建/修改草稿 | 重读目标 ID、关键字段、范围、修订号；确保未覆盖无关数据 |
| Skill 发布 | 目标版本为 published，default_version_id 指向目标；记录 version_id 与 sha256 |
| 专家发布 | current_release 的版本/ID与目标一致；check 通过不等于真实专家执行 |
| MCP 配置/发现 | 详情字段、enabled/连接状态、能力 key 和策略；发现不等于每个工具已测试 |
| MCP 执行 | 检查嵌套工具 isError、业务结果和 activities，不能只看 HTTP 成功 |
| 下架/删除 | 重读确认下架状态或实际不存在，依赖影响单独说明 |
| 下载 | CLI 校验成功、文件路径/大小/摘要；不自动解压运行 |

交付以“已做什么、落在哪个平台/组织/ID、真实核验到哪一步、剩余阻塞”为主。批量任务逐项记录成功、失败和未执行；不把部分成功说成全部完成。发生平台不兼容、权限不足、缺少精确依赖或外部操作授权不明时，保留可审阅输入并说明阻塞，不绕过 CLI 权限。
