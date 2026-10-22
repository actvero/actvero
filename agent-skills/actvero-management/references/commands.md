# 命令与请求字段索引

命令来源是本版本 CLI。用 `actvero <组> <子命令> --help` 获取准确选项，不猜别名；资源均需 `--server <基础URL> --org <组织UUID>`。默认 stdout 为格式化 JSON，--json 为单行。写命令支持 --request-id；只读命令一般不支持。

## 离线和平台入口

| 命令 | 结果/用途 |
| --- | --- |
| --version / --help | 版本与命令树 |
| guide list / guide show <topic> | 主题列表 / {topic,content}；overview、bootstrap、operations、skills、mcp、experts、recovery、commands |
| schema list / schema show <Name> | 可用模型及契约来源 / 自含 $defs 的 JSON Schema |
| example list / example show <name> | expert、mcp、mcp-run、skill-metadata、mcp-builtin；show 直接输出示例对象 |
| agent-skill path | 本 npm 包内 Skill 路径 |
| agent-skill install --to <skills父目录> | 创建 actvero-management 子目录，存在则拒绝覆盖；不修改 Agent 的其它设置 |
| platform info --server <URL> | 无登录读取 Metadata，检查部署能力 |
| auth login [--write] [--reauthenticate] | 浏览器登录，需当前机器凭据库；两个参数含义见 bootstrap |
| auth status / auth logout | 当前所选平台 CLI 身份 / 退出 |
| org list [--page N] | 组织分页，不带 --org |
| org show / org permissions | 需 --org，当前组织与权限 |
| channels list [--q TEXT] [--page N] [--state current或archived或all] / channels show <ID> | 渠道只读查询，无渠道写入能力 |
| commands show <REQUEST_UUID> | 本人在该组织的写操作回执 |

## Skills

| 命令 | 输入/关键选项 | 响应参考 |
| --- | --- | --- |
| skills list | --q / --category / --status published或unpublished / --page | result.items 为 SkillView |
| skills show <ID> | — | SkillView |
| skills preview <ZIP> | 原始 ZIP ≤20 MiB | SkillPreview |
| skills import <ZIP> | --version；可选 --metadata FILE、--skill UUID、--revision N；后两者已有技能需同时提供 | SkillImport（CLI 补包数据），SkillView |
| skills update <ID> | --file FILE：SkillUpdate | SkillView |
| skills publish/withdraw <ID> | --version-id UUID --revision N | SkillView |
| skills delete-draft <ID> | --version-id UUID --revision N | 确认结果，重读详情 |
| skills files <ID> | --version-id UUID | SkillOverview，SKILL.md 文本 |
| skills file <ID> | --version-id UUID --path 包内精确路径 | SkillFileContent |
| skills icons | — | result 数组 SkillIconOption |
| skills download <ID> | --version-id UUID --out 新路径；写授权 | {request_id,org_id,path,sha256,size} |
| skills distributions | --skill UUID（可选）/ --page | SkillDistributionPage |

SkillImport 的 metadata 仅负责 display_name/description/audience/member_ids/category/icon_selection/release_notes。SkillImport schema 包含 CLI 生成的字段，不要求 Agent 手工写 base64。

## MCP

| 命令 | --file schema / 选项 |
| --- | --- |
| mcp list / show <ID> | McpServiceView；list 无分页 |
| mcp create / update <ID> | McpServiceWrite / McpServiceUpdate |
| mcp delete <ID> | --version 当前整数版本 |
| mcp presentation <ID> | McpPresentationUpdate |
| mcp capabilities <ID> / discover <ID> | 查询目录 / 实际网络发现 |
| mcp policy <ID> | McpPolicyInput |
| mcp connect <ID> / disconnect <ID> | McpCredentials / 无文件 |
| mcp preview-import / import | McpImport 或 McpImportRequest；import 写入 |
| mcp export | 读取脱敏 McpImport |
| mcp run <ID> | McpRun；实际执行，含副作用可能 |
| mcp activities | --category call或connection 必填；可选 --service、--result success或failed或timeout、--q、--since、--until、--page |
| mcp contents list / create / update <ID> / delete <ID> | 创建/更新 McpContentInput；list 无分页 |
| mcp oauth start <SERVICE_UUID> | 可选 --no-browser；ManagementOAuthView |
| mcp oauth status/complete/cancel <ATTEMPT_UUID> | 无输入文件；status 读取，后两者写入 |

服务结构/连接/执行字段见 [MCP](mcp.md)。schema 并不含供应商每个工具的参数形状；运行时从 capabilities 的 definition.inputSchema 获取。

## 专家和分类

| 命令 | 输入 schema / 选项 |
| --- | --- |
| experts list | --q / --category / --status published或unpublished / --page |
| experts show/check <ID> | ExpertView / 仅其 check 对象 |
| experts create/update <ID> | create 不带 ID，--file ExpertSave / ExpertUpdate |
| experts scope <ID> | --file ExpertScope |
| experts refresh-skills <ID> | --file ExpertSkillRefresh；精确更新 body.request_id 和外层 --request-id 作用不同 |
| experts publish <ID> | --revision N --version X.Y.Z，可选 --notes |
| experts withdraw/delete <ID> | --revision N |
| experts dependencies | --kind skills或connectors 必填；--q / --page |
| experts dependency <ID> | --kind skills或connectors；技能可选 --version-id |
| experts skill-impact | --skill UUID 必填；--target-version / --source-version / --q / --page |
| experts dependency-command <ID> | DependencyCommandView |
| skills/experts categories list | 当前分类 ID、name、count、revision、system |
| skills/experts categories create | --name |
| skills/experts categories rename <ID> | --name --revision N |
| skills/experts categories move <ID> | --direction up或down --revision N |
| skills/experts categories delete <ID> | --target ID --count N --revision N |

## Schema 的边界和维护

`schema show` 是从平台 OpenAPI 提取的本地契约快照，可查询嵌套模型。数字范围、长度、枚举、必填/可选、additionalProperties 均以快照为准；服务端额外验证组织权限、成员范围、图片、URL、哈希、依赖状态等。

这些 schema 不启动网络、不自动验证请求，也不证明目标平台已升级。先 platform info，再根据实际返回调整操作；不接受不兼容能力时报告，而非尝试强行调用。

维护 CLI 的开发者在明确选定平台契约后运行 `node scripts/sync-schemas.mjs <openapi.json>`，更新公开 schema、手册和测试。npm 安装/构建不读取相邻项目，终端用户不需要平台源码。
