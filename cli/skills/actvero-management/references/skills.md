# Skills：包、资料、版本与分类

先完成 [初始化](bootstrap.md) 和 [共同操作规则](operations.md)。以下所有平台命令都加 `--server <SERVER> --org <ORG_UUID> --json`；示例省略仅为便于阅读。写入及下载需 write 会话。

## 查询和文件阅读

```sh
actvero skills list --q "摘要" --page 1
actvero skills list --category <CATEGORY_ID> --status published --page 1
actvero skills show <SKILL_UUID>
actvero skills files <SKILL_UUID> --version-id <VERSION_UUID>
actvero skills file <SKILL_UUID> --version-id <VERSION_UUID> --path document-summary/SKILL.md
```

列表 status 为 published/unpublished。详情 result 含 `id/name/display_name/description/audience/member_ids/category/revision/default_version_id/versions`。每个版本有 `id/version/status/sha256/size/files`；文件含 path/size/sha256/previewable。

**files 命令返回 SKILL.md 概览文本 `result.content`，不是文件清单**。真正文件清单读 `show.result.versions[].files` 或 preview。单文件路径必须取自清单（可能带技能目录前缀），只读可预览文本，不猜 `SKILL.md` 总在根目录。

## 新建：准备 ZIP → 预览 → 导入草稿 → 发布

1. 整理一个技能目录，唯一 SKILL.md，UTF-8 YAML frontmatter：

   ```markdown
   ---
   name: document-summary
   description: 根据用户提供的文档整理摘要、决策和待办事项。
   ---
   # Document summary
   仅依据提供的材料整理结果；缺失信息明确标记，不编造。
   ```

   可以附 scripts/references/assets。若 ZIP 有一级目录，目录名须等于 name，所有文件在该目录下；也可直接把内容放根。name 为小写字母/数字/单个连字符、不超过 64；description 1–1024 字符。不能打包父项目目录、另一个嵌套 Skill、凭据或过程文档。
2. ZIP ≤20 MiB，解压总大小 ≤40 MiB，单文件 ≤5 MiB，最多 500 个文件/目录条目；SKILL.md ≤256 KiB。禁止符号链接、特殊文件、加密 ZIP、路径穿越、重复路径、.git/node_modules/缓存和真实 .env 文件。CLI 不执行包内脚本。
3. 预览：

   ```sh
   actvero skills preview ./document-summary.zip
   actvero example show skill-metadata > ./skill-metadata.json
   ```

   核对返回 name、description、files、sha256 和 icon_warning；编辑 metadata 中 display_name、description、audience、member_ids、category、release_notes。不传 metadata 时默认使用包内名称/描述、范围 administrators；不会自动向全部成员开放。
4. 导入：

   ```sh
   actvero skills import ./document-summary.zip --version 1.0.0 --metadata ./skill-metadata.json
   ```

   从实际响应/重读详情取技能 ID 和新草稿版本 UUID，不能用字符串版本 `1.0.0` 代替 UUID。版本号支持 X.Y.Z 或 X.Y.Z-prerelease，最大 50 字符；元数据约束见 `schema show SkillImport`。package_base64、version、skill_id、revision 由 CLI 生成/参数提供，无需手写在 metadata。
5. 用户目标包含发布时，重读最新 revision，然后：

   ```sh
   actvero skills publish <SKILL_UUID> --version-id <VERSION_UUID> --revision <REVISION>
   actvero skills show <SKILL_UUID>
   ```

   核验指定版本 published 且 default_version_id 一致。仅要求上传/保存草稿时停止于草稿核验，不擅自发布。

## 为已有技能新增版本

先查询目标技能和当前 revision，核对包内 name 与现有技能匹配。预览新 ZIP，读取 metadata 并保留已有范围/分类，再：

```sh
actvero skills import ./document-summary.zip --skill <SKILL_UUID> --revision <REVISION> --version 1.1.0 --metadata ./skill-metadata.json
```

重新查详情选择新 draft；用户要求生效才发布。一次只有一个生效发布版本，旧生效版成为 superseded，保留历史；引用旧版的专家不会因此自动更新。先用 `experts skill-impact` 查影响，按 [专家精确依赖升级](experts.md) 处理已授权专家，不能将发布技能说成已升级所有专家。

## 修改展示资料、范围、图标

`skills update <ID> --file ./skill-update.json` 接收 SkillUpdate：

```json
{
  "display_name": "文档摘要",
  "description": "从文档提取摘要和待办事项。",
  "audience": "administrators",
  "member_ids": [],
  "revision": 1
}
```

示例 revision 必须换成实际值，其他字段应从当前详情保留后改指定字段。category 是字符串 ID，省略/null 保持原分类，显式 `uncategorized` 移到未分类。icon_selection 省略/null 保持；`{"source":"auto"}` 恢复跟随包内图标，library 的 key 取 `skills icons`；upload 使用合法 PNG/JPEG/WebP data URL，具体限额/校验以平台为准。不要填外部图标 URL。

## 下架、删除草稿、下载

```sh
actvero skills withdraw <SKILL_UUID> --version-id <VERSION_UUID> --revision <REVISION>
actvero skills delete-draft <SKILL_UUID> --version-id <VERSION_UUID> --revision <REVISION>
actvero skills download <SKILL_UUID> --version-id <VERSION_UUID> --out ./downloaded-skill.zip --request-id <REQUEST_UUID>
actvero skills distributions --skill <SKILL_UUID> --page 1
```

withdraw 保留版本历史，可能影响依赖可用性；先读 impact 并按授权范围处置。delete-draft 只能删除从未发布的草稿，不是删除整项技能或任意历史版本。

下载因记录一次分发需要写授权，CLI 核对组织、请求编号、响应类型、20 MiB 和 SHA-256。不覆盖已有输出、不自动解压/执行；可指定不存在的新路径，父目录需可写。下载中断先回查，原编号恢复不会重复记录该次分发，访问权限仍重新验证。分发记录不是最终桌面已安装或成功执行的证明。

## 分类（Skills 和专家通用流程）

```sh
actvero skills categories list
actvero skills categories create --name 文档处理
actvero skills categories rename <CATEGORY_ID> --name 文档工具 --revision <REVISION>
actvero skills categories move <CATEGORY_ID> --direction up --revision <REVISION>
actvero skills categories delete <CATEGORY_ID> --target uncategorized --count <COUNT> --revision <REVISION>
```

分类名称 1–30 字符；ID 从 list/result 数组取得，不从中文名推导。移动方向 up/down。删除前读取当前 count/revision 并选合法迁入类别；删除只迁移资源，不删除资源。数量/修订变化返回 409，重新查看影响再执行。系统 uncategorized 不可改名/移动/删除。专家分类命令只需将 skills 换成 experts。
