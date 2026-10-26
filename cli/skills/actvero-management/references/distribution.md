# 客户端发布：存储、上传与通道

此入口使用独立平台授权，不需要 `--org`。先检查 `platform info` 中的 `client_distribution.read/write`，再运行 `auth status --target platform`；需要时用 `auth login --target platform` 在浏览器授权维护文件、发布版本和管理存储。组织会话不能代替平台会话。

## 操作顺序

1. `storage list` 读取已有配置。新增或修改用 `storage save <UUID> --file <JSON>`，字段见 `schema show StorageSave`；包含 expected_revision，已有密钥留空保留。保存后用 `storage test <UUID>` 检查。
2. 从桌面构建输出取得 `client-release.json`，运行 `releases import --file <JSON> --storage <UUID>`。清单含 schema_version=1、version、channel、minimum_os、feed_roots 与 artifacts；每个文件提供 target、role、相对 file、size_bytes 和 base64 SHA-512。CLI 在写入前检查摘要和更新源。不同架构可依次导入同一个未发布版本。
3. 导入返回草稿和文件状态。使用 `releases show <UUID>`、`releases jobs --artifact <UUID>` 回查；失败后可 `releases verify <artifact UUID>` 重试校验。
4. 所需文件均已校验后，读取当前 revision，运行 `releases plan <UUID> --revision <n> --targets win-x64,mac-arm64,mac-x64`，只列出本次实际发布的目标。核对计划后，用 `releases publish <UUID> --plan <plan UUID>` 发布。
5. `releases heads` 与 `releases show` 回查结果。下架使用 `releases withdraw <UUID> --revision <n>`，不自动降级或切回旧版本。

每条联网命令均显式带 `--server <URL>`。导入和校验不会自动发布；发布属于用户任务授权范围时可继续执行，无需按本手册另加确认。

## 上传与恢复

清单导入使用稳定版本和文件编号。传输中断后使用原清单、原文件与同一平台重试；有声明摘要的文件可跳过已确认分片。合并响应不明时先回查远端对象，不重新创建一个版本。`releases upload-status <artifact UUID>` 查看任务，`releases upload <artifact UUID> <file>` 恢复本地文件传输。没有声明 SHA-512 的上传恢复会重传分片，避免混合不同文件。

已有地址用 `releases artifact-add <release UUID> <artifact UUID> --file <JSON>`，字段见 `schema show ArtifactCreate`。长期引用不能带查询参数；临时 URL 使用 mirror=true 和 storage_id 转存。不要在聊天、日志或提交文件中放入存储密钥、临时 URL 凭据或签名上传地址。

未完成的任务可用 `releases upload-abort <artifact UUID>` 取消，再用 `releases artifact-remove <artifact UUID> --revision <n>` 移除草稿登记。文件记录移除不直接删除桶内对象。过期任务需要取消并重新登记。

发布计划有效期 15 分钟；409 先读取版本和通道状态，再生成新计划。同一发布计划可以重复提交回查，不能换一个计划去猜测上次是否成功。这组接口使用资源编号、expected_revision 和 plan_id 恢复，不使用组织资源的 `commands show` 回执。

## 文件与更新边界

Windows x64 提供 EXE 和 EXE.blockmap；Mac 每个架构提供 DMG、ZIP、ZIP.blockmap。版本采用 SemVer，latest 不接受预发布号。首次发布冻结整个版本的文件与资料，请先准备全部目标。已准备的目标可分批发布；补新文件使用新版本。

安装包必须用目标平台 feed 构建并完成签名；旧客户端不会自动改用新的更新地址。差分由 electron-updater 和配套 blockmap 执行，不保证每次都能增量下载。Mac 缺少旧 ZIP 缓存时可能全量下载。平台文件校验不是签名验证或真实安装升级验收。
