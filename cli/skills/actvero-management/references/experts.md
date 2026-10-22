# 专家：草稿、依赖与不可变发布

先完成 [初始化](bootstrap.md) 和 [共同规则](operations.md)。所有平台命令加 `--server <SERVER> --org <ORG_UUID> --json`。专家是平台上的配置资源；CLI 维护草稿和发布版本，不执行专家对话，也不导入桌面专家 ZIP。

## 新建到发布

```sh
actvero experts list --q "文档助手" --page 1
actvero experts categories list
actvero example show expert > ./expert.json
actvero schema show ExpertSave
actvero experts create --file ./expert.json
actvero experts show <EXPERT_UUID>
actvero experts check <EXPERT_UUID>
```

示例生成完整可编辑请求。顶层 content 是专家草稿，category 为当前分类 ID（默认 uncategorized）。content 字段：

| 字段 | 规则 |
| --- | --- |
| name/description | 必填；1–80 / 1–500 字符 |
| instructions | 最多 64000 字符；发布需满足服务端内容校验 |
| avatar/tags | avatar 为受支持图片 data URL 或空；最多 8 个标签，每个 1–30 字符 |
| conversation_starters | 最多 6 条，每条 1–1000 字符 |
| skills/connectors | 各最多 32 项；同类 key 唯一，同一资源不重复引用 |

长度还按 UTF-16 单位校验，不要用 Emoji 等绕过限制。不能附加任意字段。

create 后从响应取 ID，show 核对 content、category、audience/member_ids、revision。需要更改使用范围，准备 ExpertScope（audience/member_ids/revision），再执行：

```sh
actvero experts scope <EXPERT_UUID> --file ./scope.json
actvero experts check <EXPERT_UUID>
```

check 返回 can_publish、instruction_missing、audience_count、dependencies；每项依赖有 status、missing_members、update_available 等。缺少必要说明/依赖/成员可用性应修复真实原因，不通过降低 required 或扩大范围绕过用户意图。

用户目标包括发布且 check 可发布时，**再次读取最新 revision**：

```sh
actvero experts publish <EXPERT_UUID> --revision <REVISION> --version 1.0.0 --notes "首次发布"
actvero experts show <EXPERT_UUID>
```

专家版本仅 X.Y.Z，不接受 Skill/npm 式 prerelease。发布生成不可变版本；核对 current_release 的 id/version/sha256，保存草稿本身不会改变已有发布内容。不能把发布资格或发布成功写成“专家已经完成真实任务测试”。

## 修改已有专家

```sh
actvero experts show <EXPERT_UUID>
actvero schema show ExpertUpdate
actvero experts update <EXPERT_UUID> --file ./expert-update.json
```

输入为 `{"content":完整内容,"category":"分类ID","revision":当前修订号}`。**详情里的 category 是 {id,name} 对象，写入需要 category.id 字符串**。保留完整 skills/connectors/tags 等数组；省略默认字段可能清空它们。使用范围由 scope 单独处理；发布也单独处理。revision 与 metadata_revision 不可随意互换，命令需要的是详情 revision。

## 添加精确 Skill 引用

```sh
actvero experts dependencies --kind skills --q "摘要" --page 1
actvero experts dependency <SKILL_UUID> --kind skills --version-id <VERSION_UUID>
actvero skills show <SKILL_UUID>
```

候选结果有 id/name/description/version_id/version/sha256/status/update_available。选择用户目标版本，确保该组织可用；取同一版本的 version_id + sha256，不把当前生效版本摘要配给旧版本。

在完整 content.skills 数组中增加：

```json
{
  "key": "document_summary",
  "label": "文档摘要",
  "required": true,
  "skill_id": "<SKILL_UUID>",
  "version_id": "<VERSION_UUID>",
  "sha256": "<来自该版本的64位小写摘要>",
  "load": "always"
}
```

占位符必须替换为真实查询值。key 是专家内稳定引用名，只允许字母数字下划线连字符、1–80 字符，不用 __proto__/constructor/prototype；label 1–120。load=always|on_demand，根据使用意图选择。完整更新后 check，不静默替换其它引用。

## 添加 MCP 引用与工具白名单

```sh
actvero experts dependencies --kind connectors --page 1
actvero experts dependency <SERVICE_UUID> --kind connectors
actvero mcp capabilities <SERVICE_UUID>
```

读取连接器候选的 tools、tools_discovered、status。content.connectors 项：

```json
{
  "key": "document_tools",
  "label": "文档工具",
  "required": true,
  "connector_id": "<SERVICE_UUID>",
  "tools": ["<实际工具名称>"]
}
```

tools 用平台返回的工具名称，不用展示名。显式白名单更便于表达本次授权；`[]` 禁用全部工具，`null` 是兼容旧版的“跟随连接器开放工具”，不是“没有工具”。保留已有 null 时说明其语义，不自行扩宽/缩窄。

服务启用、能力策略、个人连接、专家使用范围都影响最终可用性。尚未发现或个人未授权时，不能凭配置存在就认定可用。按 MCP 手册补齐已授权连接/发现，再 check。

## 已发布 Skill 的精确升级

1. 查更新影响与目标版本：

   ```sh
   actvero experts skill-impact --skill <SKILL_UUID> --target-version <TARGET_VERSION_UUID> --page 1
   actvero experts show <EXPERT_UUID>
   actvero experts dependency <SKILL_UUID> --kind skills --version-id <TARGET_VERSION_UUID>
   ```

   分页收集已授权专家；可加 source-version/q 过滤。区分 draft_versions、published_versions 和 draft_changes，发布引用与草稿可能不同。
2. 生成一个请求 UUID，准备 ExpertSkillRefresh：

   ```json
   {
     "revision": 1,
     "request_id": "<REQUEST_UUID>",
     "changes": [{
       "key": "document_summary",
       "from_version_id": "<CURRENT_DRAFT_VERSION_UUID>",
       "from_sha256": "<CURRENT_DRAFT_SHA256>",
       "to_version_id": "<TARGET_VERSION_UUID>",
       "to_sha256": "<TARGET_SHA256>"
     }]
   }
   ```

   revision/from 来自刚读取的专家草稿，to 来自目标 Skill 版本；changes 仅列授权的 key（最多 32）。不要用旧发布引用代替当前草稿。body 的 request_id 是依赖更新回执编号，CLI 的 --request-id 是外层管理请求编号，推荐两者使用同一个新 UUID，便于关联。
3. 提交并读回：

   ```sh
   actvero experts refresh-skills <EXPERT_UUID> --file ./skill-refresh.json --request-id <REQUEST_UUID>
   actvero experts dependency-command <REQUEST_UUID>
   actvero experts show <EXPERT_UUID>
   actvero experts check <EXPERT_UUID>
   ```

   只更新草稿。若用户要求发布新专家版本，再用新的最新 revision 和未使用的 X.Y.Z 发布；否则报告草稿已更新，旧发布版保持原依赖。优先显式 changes，避免 revision-only 旧兼容路径扩大更新范围。

## 下架、删除与分类

```sh
actvero experts withdraw <EXPERT_UUID> --revision <REVISION>
actvero experts delete <EXPERT_UUID> --revision <REVISION>
```

下架保留草稿与历史，核验 current_release/发布状态；删除会删除专家和其发布版本，不删除所引用的 Skills/MCP。只想停止使用应按用户意图下架，不能替换成删除。删除结果未知先回查 request_id，再查资源。

分类支持 list/create/rename/move/delete，参数与 [Skills 分类](skills.md) 相同，将 skills 换成 experts；分类删除迁移专家而非删除专家。
